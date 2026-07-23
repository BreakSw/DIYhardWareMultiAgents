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
        payload = {
            "task": (
                "Classify the latest user_text semantically. The latest message is authoritative; "
                "conversation_context is only supporting context for references and follow-up details. "
                "In-scope requests include building a desktop PC, selecting or upgrading PC hardware, "
                "completing a build around an owned component, checking compatibility, or planning a "
                "workstation. Friendly greetings, thanks, and social messages without a current hardware "
                "request are casual; unrelated requests are off_topic. Do not use a keyword whitelist. "
                "For casual or off_topic messages, write a concise, warm assistant_reply that responds "
                "naturally and invites the user to discuss PC building. For in-scope requests, leave "
                "assistant_reply empty. Keep is_pc_build_request consistent with request_type."
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
        }
        first = self.brain.invoke_agent(
            self.name,
            payload,
            IntentClassification,
        )
        attempts = [first]
        if first.get("status") == "success" and self._is_inconsistent(first.get("result", {})):
            reflected = self.brain.invoke_agent(
                self.name,
                {
                    **payload,
                    "task": (
                        "Reflect on the previous decision because its fields are internally inconsistent. "
                        "Re-read the latest user_text, treat it as authoritative, and return one corrected "
                        "classification. The boolean must be true exactly for pc_build, pc_upgrade, or "
                        "hardware_consultation. A casual/off_topic decision must include assistant_reply."
                    ),
                    "previous_decision": first.get("result", {}),
                },
                IntentClassification,
            )
            attempts.append(reflected)
        result = dict(attempts[-1])
        result["attempt_responses"] = attempts
        return result

    @staticmethod
    def _is_inconsistent(decision: dict[str, Any]) -> bool:
        request_type = decision.get("request_type")
        in_scope_type = request_type in {
            "pc_build",
            "pc_upgrade",
            "hardware_consultation",
        }
        if bool(decision.get("is_pc_build_request")) != in_scope_type:
            return True
        return not in_scope_type and not str(decision.get("assistant_reply") or "").strip()
