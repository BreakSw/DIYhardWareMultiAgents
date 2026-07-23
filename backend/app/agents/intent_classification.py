from __future__ import annotations

from typing import Any

from app.services.llm_client import IntentClassification


class IntentClassificationAgent:
    """Use the LLM to decide whether a request belongs to the PC-building domain."""

    name = "IntentClassificationAgent"

    def __init__(self, brain: Any) -> None:
        self.brain = brain

    def run(self, user_text: str) -> dict[str, Any]:
        return self.brain.invoke_agent(
            self.name,
            {
                "task": (
                    "Classify the user's intent semantically. In-scope requests include building a "
                    "desktop PC, selecting or upgrading PC hardware, checking compatibility, or "
                    "planning a workstation. Questions unrelated to those tasks are off-topic. "
                    "Do not use a keyword whitelist and do not answer the user's request."
                ),
                "user_text": user_text,
                "decision_policy": {
                    "pc_build": "A complete desktop configuration or purchase plan.",
                    "pc_upgrade": "Upgrade, replace, or complete existing desktop hardware.",
                    "hardware_consultation": "Compatibility or component-selection advice that can feed a build.",
                    "off_topic": "Anything outside desktop building and related hardware decisions.",
                },
            },
            IntentClassification,
        )
