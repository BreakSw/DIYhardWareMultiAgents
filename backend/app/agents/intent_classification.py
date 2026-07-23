from __future__ import annotations

from typing import Any

from app.services.llm_client import IntentClassification


class IntentClassificationAgent:
    """Use the LLM to decide whether a request belongs to the PC-building domain."""

    name = "IntentClassificationAgent"

    def __init__(self, brain: Any) -> None:
        self.brain = brain

    def run(
        self,
        user_text: str,
        context: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        return self.brain.invoke_agent(
            self.name,
            {
                "task": (
                    "Classify the user's intent semantically. In-scope requests include building a "
                    "desktop PC, selecting or upgrading PC hardware, checking compatibility, or "
                    "planning a workstation. Friendly greetings, thanks, and social messages are "
                    "casual; unrelated requests are off_topic. Do not use a keyword whitelist. "
                    "For casual or off_topic messages, write a concise, warm assistant_reply that "
                    "responds naturally and invites the user to discuss PC building. For in-scope "
                    "requests, leave assistant_reply empty."
                ),
                "user_text": user_text,
                "conversation_context": context or [],
                "decision_policy": {
                    "pc_build": "A complete desktop configuration or purchase plan.",
                    "pc_upgrade": "Upgrade, replace, or complete existing desktop hardware.",
                    "hardware_consultation": "Compatibility or component-selection advice that can feed a build.",
                    "casual": "Greeting, thanks, or friendly social conversation without a hardware request.",
                    "off_topic": "Anything outside desktop building and related hardware decisions.",
                },
            },
            IntentClassification,
        )
