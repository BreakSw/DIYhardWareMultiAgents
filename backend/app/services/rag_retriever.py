from __future__ import annotations

import hashlib
import json
import math
import re
import threading
from pathlib import Path
from typing import Any

import httpx

from app.core.config import ROOT_DIR, settings
from app.knowledge.retrieval import load_catalog_records


class VoyageEmbeddingClient:
    """Small Voyage REST client used for document and query embeddings."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model_name: str,
        dimension: int,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_name = model_name
        self.dimension = dimension
        self.timeout = timeout

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), 64):
            vectors.extend(self._embed(texts[start : start + 64], "document"))
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], "query")[0]

    def _embed(self, texts: list[str], input_type: str) -> list[list[float]]:
        with httpx.Client(trust_env=False, timeout=self.timeout) as client:
            response = client.post(
                f"{self.base_url}/embeddings",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "input": texts,
                    "model": self.model_name,
                    "input_type": input_type,
                    "output_dimension": self.dimension,
                    "output_dtype": "float",
                    "truncation": True,
                },
            )
            response.raise_for_status()
            payload = response.json()
        ordered = sorted(payload.get("data", []), key=lambda item: item.get("index", 0))
        vectors = [item.get("embedding") for item in ordered]
        if len(vectors) != len(texts) or any(not isinstance(item, list) for item in vectors):
            raise ValueError("Voyage returned an invalid embedding response")
        return vectors


class CatalogRagRetriever:
    """Hybrid vector/lexical retrieval over the published hardware catalog."""

    def __init__(
        self,
        catalog_directory: Path | str,
        *,
        embedding_client: Any | None = None,
        cache_directory: Path | str | None = None,
        include_partial: bool = True,
        default_top_k: int = 16,
        vector_weight: float = 0.8,
    ) -> None:
        self.catalog_directory = Path(catalog_directory)
        self.embedding_client = embedding_client
        self.cache_directory = Path(cache_directory or self.catalog_directory.parent / "index")
        self.include_partial = include_partial
        self.default_top_k = max(1, default_top_k)
        self.vector_weight = min(1.0, max(0.0, vector_weight))
        self._lock = threading.RLock()

    def retrieve(self, query: str, *, top_k: int | None = None) -> dict[str, Any]:
        query = query.strip()
        if not query:
            return self._failure("RAG query is empty")
        try:
            records = load_catalog_records(
                self.catalog_directory,
                include_partial=self.include_partial,
            )
        except Exception as exc:
            return self._failure(str(exc))
        if not records:
            return self._failure("Hardware knowledge catalog is empty")

        documents = [self._document(record) for record in records]
        lexical_scores = [self._lexical_score(query, document) for document in documents]
        mode = "lexical"
        vector_scores = [0.0] * len(records)
        vector_error: str | None = None
        if self.embedding_client is not None:
            try:
                vectors = self._document_vectors(documents)
                query_vector = self.embedding_client.embed_query(query)
                vector_scores = [self._cosine(query_vector, vector) for vector in vectors]
                mode = "vector"
            except Exception as exc:
                vector_error = str(exc)[:300]

        scored: list[tuple[float, int]] = []
        for index, record in enumerate(records):
            quality_bonus = 0.03 if record.get("quality_level") == "verified" else 0.0
            if mode == "vector":
                score = (
                    self.vector_weight * vector_scores[index]
                    + (1.0 - self.vector_weight) * lexical_scores[index]
                    + quality_bonus
                )
            else:
                score = lexical_scores[index] + quality_bonus
            scored.append((score, index))
        scored.sort(key=lambda item: item[0], reverse=True)
        selected = self._diverse_indices(scored, records, top_k or self.default_top_k)
        results = [self._evidence(records[index], score) for score, index in selected]
        return {
            "status": "success",
            "provider": "local-rag",
            "retrieval_mode": mode,
            "query": query,
            "result_count": len(results),
            "catalog_count": len(records),
            "results": results,
            "vector_error": vector_error,
            "error": None,
        }

    def _document_vectors(self, documents: list[str]) -> list[list[float]]:
        fingerprint = hashlib.sha256(
            (self.embedding_client.model_name + "\n" + "\n".join(documents)).encode("utf-8")
        ).hexdigest()
        cache_path = self.cache_directory / f"{fingerprint}.json"
        with self._lock:
            if cache_path.exists():
                payload = json.loads(cache_path.read_text(encoding="utf-8"))
                vectors = payload.get("vectors", [])
                if len(vectors) == len(documents):
                    return vectors
            vectors = self.embedding_client.embed_documents(documents)
            if len(vectors) != len(documents):
                raise ValueError("Embedding count does not match catalog record count")
            self.cache_directory.mkdir(parents=True, exist_ok=True)
            temporary = cache_path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(
                    {
                        "fingerprint": fingerprint,
                        "model": self.embedding_client.model_name,
                        "record_count": len(documents),
                        "vectors": vectors,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            temporary.replace(cache_path)
            return vectors

    @staticmethod
    def _document(record: dict[str, Any]) -> str:
        price = record.get("price") if isinstance(record.get("price"), dict) else {}
        return json.dumps(
            {
                "category": record.get("category"),
                "brand": record.get("brand"),
                "model": record.get("model"),
                "market": record.get("market"),
                "specs": record.get("specs", {}),
                "reference_cny": price.get("reference_cny"),
                "reference_usd": price.get("reference_usd"),
                "quality_level": record.get("quality_level"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    @classmethod
    def _lexical_score(cls, query: str, document: str) -> float:
        query_tokens = cls._tokens(query)
        if not query_tokens:
            return 0.0
        document_tokens = cls._tokens(document)
        overlap = sum(1 for token in query_tokens if token in document_tokens)
        return overlap / math.sqrt(len(query_tokens) * max(1, len(document_tokens)))

    @staticmethod
    def _tokens(text: str) -> set[str]:
        lowered = text.lower()
        tokens = set(re.findall(r"[a-z0-9]+(?:[.-][a-z0-9]+)*", lowered))
        for run in re.findall(r"[\u4e00-\u9fff]+", lowered):
            tokens.update(run[index : index + 2] for index in range(max(1, len(run) - 1)))
        return tokens

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        if len(left) != len(right) or not left:
            raise ValueError("Embedding dimensions do not match")
        dot = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0

    @staticmethod
    def _diverse_indices(
        scored: list[tuple[float, int]],
        records: list[dict[str, Any]],
        limit: int,
    ) -> list[tuple[float, int]]:
        selected: list[tuple[float, int]] = []
        selected_indices: set[int] = set()
        categories: set[str] = set()
        for score, index in scored:
            category = str(records[index].get("category") or "other")
            if category not in categories:
                selected.append((score, index))
                selected_indices.add(index)
                categories.add(category)
                if len(selected) >= limit:
                    return selected
        for score, index in scored:
            if index not in selected_indices:
                selected.append((score, index))
                if len(selected) >= limit:
                    break
        return selected

    @staticmethod
    def _evidence(record: dict[str, Any], score: float) -> dict[str, Any]:
        price = record.get("price") if isinstance(record.get("price"), dict) else {}
        sources = record.get("sources") if isinstance(record.get("sources"), list) else []
        offers = price.get("offers") if isinstance(price.get("offers"), list) else []
        link = sources[0] if sources else (offers[0].get("url") if offers else "")
        title = " ".join(
            str(value).strip() for value in [record.get("brand"), record.get("model")] if value
        )
        return {
            "title": title or "Unnamed hardware record",
            "link": link,
            "source": f"local-rag:{record.get('quality_level', 'unknown')}",
            "price": price.get("reference_cny"),
            "price_usd": price.get("reference_usd"),
            "category": record.get("category"),
            "specs": record.get("specs", {}),
            "market": record.get("market"),
            "fetched_at": record.get("fetched_at"),
            "retrieval_score": round(float(score), 6),
        }

    @staticmethod
    def _failure(error: str) -> dict[str, Any]:
        return {
            "status": "failed",
            "provider": "local-rag",
            "retrieval_mode": "none",
            "result_count": 0,
            "catalog_count": 0,
            "results": [],
            "error": error[:500],
        }


def build_catalog_rag_retriever() -> CatalogRagRetriever:
    embedding_client = None
    if settings.rag_enabled and settings.embedding_api_key and settings.embedding_model:
        embedding_client = VoyageEmbeddingClient(
            base_url=settings.embedding_base_url,
            api_key=settings.embedding_api_key,
            model_name=settings.embedding_model,
            dimension=settings.embedding_dimension,
        )
    catalog = ROOT_DIR / "backend" / "data" / "knowledge" / "hardware" / "catalog" / "current"
    return CatalogRagRetriever(
        catalog,
        embedding_client=embedding_client,
        default_top_k=settings.rag_top_k,
        vector_weight=settings.rag_vector_weight,
    )
