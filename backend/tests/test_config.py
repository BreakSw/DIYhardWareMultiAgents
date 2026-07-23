from pathlib import Path

from app.core.config import Settings


def test_loads_project_and_rag_settings_from_dotenv(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "app-env=dev",
                "log-level=INFO",
                "url=https://api.example.com",
                "api-key=test-llm-key",
                "model=test-model",
                "llm-timeout=45",
                "serpapi-key=test-search-key",
                "mysql-url=mysql+pymysql://user:pass@localhost/project",
                "rag-enabled=true",
                "embedding-base-url=https://api.voyageai.com/v1",
                "embedding-model=voyage-code-3",
                "embedding-api-key=test-embedding-key",
                "embedding-dimension=1024",
                "qdrant-url=https://qdrant.example.com",
                "qdrant-api-key=test-qdrant-key",
                "qdrant-collection=diy_multiagents_knowledge",
                "qdrant-distance=cosine",
                "qdrant-timeout=10",
            ]
        ),
        encoding="utf-8",
    )

    loaded = Settings.from_env_file(env_file)

    assert loaded.model_timeout == 45
    assert loaded.rag_enabled is True
    assert loaded.embedding_base_url == "https://api.voyageai.com/v1"
    assert loaded.embedding_dimension == 1024
    assert loaded.qdrant_collection == "diy_multiagents_knowledge"
    assert loaded.qdrant_distance == "cosine"
    assert loaded.qdrant_timeout == 10
