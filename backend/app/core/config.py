from dataclasses import dataclass
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[3]


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _parse_positive_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _parse_ratio(value: str | None, default: float) -> float:
    if value is None:
        return default
    try:
        parsed = float(value)
    except ValueError:
        return default
    return parsed if 0.0 <= parsed <= 1.0 else default


@dataclass(frozen=True)
class Settings:
    app_env: str = "dev"
    log_level: str = "INFO"
    model_base_url: str = "https://api.deepseek.com"
    model_api_key: str = ""
    model_name: str = "deepseek-v4-pro"
    model_timeout: int = 60
    rag_enabled: bool = False
    rag_top_k: int = 16
    rag_vector_weight: float = 0.8
    live_search_enabled: bool = False
    embedding_base_url: str = "https://api.voyageai.com/v1"
    embedding_model: str = ""
    embedding_api_key: str = ""
    embedding_dimension: int = 1024
    serpapi_key: str = ""
    mysql_url: str = "mysql+pymysql://root:123456@127.0.0.1:3306/diy_agents"
    redis_url: str = "disabled"
    qdrant_url: str = "disabled"
    qdrant_api_key: str = ""
    qdrant_collection: str = "diy_multiagents_knowledge"
    qdrant_distance: str = "cosine"
    qdrant_timeout: int = 10

    @classmethod
    def from_env_file(cls, path: Path = ROOT_DIR / ".env") -> "Settings":
        raw = _read_env_file(path)
        return cls(
            app_env=raw.get("app-env", cls.app_env),
            log_level=raw.get("log-level", cls.log_level),
            model_base_url=raw.get("url", cls.model_base_url),
            model_api_key=raw.get("api-key", cls.model_api_key),
            model_name=raw.get("model", cls.model_name),
            model_timeout=_parse_positive_int(raw.get("llm-timeout"), cls.model_timeout),
            rag_enabled=_parse_bool(raw.get("rag-enabled"), cls.rag_enabled),
            rag_top_k=_parse_positive_int(raw.get("rag-top-k"), cls.rag_top_k),
            rag_vector_weight=_parse_ratio(
                raw.get("rag-vector-weight"), cls.rag_vector_weight
            ),
            live_search_enabled=_parse_bool(
                raw.get("live-search-enabled"), cls.live_search_enabled
            ),
            embedding_base_url=raw.get("embedding-base-url", cls.embedding_base_url),
            embedding_model=raw.get("embedding-model", cls.embedding_model),
            embedding_api_key=raw.get("embedding-api-key", cls.embedding_api_key),
            embedding_dimension=_parse_positive_int(
                raw.get("embedding-dimension"),
                cls.embedding_dimension,
            ),
            serpapi_key=raw.get("serpapi-key", cls.serpapi_key),
            mysql_url=raw.get("mysql-url", cls.mysql_url),
            redis_url=raw.get("redis-url", cls.redis_url),
            qdrant_url=raw.get("qdrant-url", cls.qdrant_url),
            qdrant_api_key=raw.get("qdrant-api-key", cls.qdrant_api_key),
            qdrant_collection=raw.get("qdrant-collection", cls.qdrant_collection),
            qdrant_distance=raw.get("qdrant-distance", cls.qdrant_distance),
            qdrant_timeout=_parse_positive_int(
                raw.get("qdrant-timeout"),
                cls.qdrant_timeout,
            ),
        )


settings = Settings.from_env_file()
