from typing import Any

from app.core.config import settings
from app.services import llm_client


def test_chat_model_uses_configured_sixty_second_timeout(monkeypatch) -> None:
    captured: dict[str, dict[str, Any]] = {}

    def fake_http_client(**kwargs):
        captured["http"] = kwargs
        return object()

    def fake_chat_openai(**kwargs):
        captured["model"] = kwargs
        return object()

    monkeypatch.setattr(llm_client.httpx, "Client", fake_http_client)
    monkeypatch.setattr(llm_client, "ChatOpenAI", fake_chat_openai)

    llm_client.DeepSeekClient._build_model()

    assert settings.model_timeout == 60
    assert captured["http"]["timeout"] == 60
    assert captured["model"]["timeout"] == 60
