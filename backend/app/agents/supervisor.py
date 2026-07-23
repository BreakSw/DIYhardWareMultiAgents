from __future__ import annotations

from typing import Any

from app.services.llm_client import AgentInsight


class SupervisorAgent:
    name = "SupervisorAgent"

    def __init__(self, brain: Any) -> None:
        self.brain = brain

    def run(self, user_text: str) -> dict[str, Any]:
        return self.brain.invoke_agent(
            self.name,
            {
                "task": "审阅用户装机请求，概括目标并指出编排关注点。不要修改预算。",
                "user_text": user_text,
            },
            AgentInsight,
        )
