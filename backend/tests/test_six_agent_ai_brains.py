from __future__ import annotations

import unittest

from app.agents.hardware_selection import HardwareSelectionAgent
from app.agents.state import AGENT_NAMES
from app.repositories.catalog import InMemoryCatalogRepository, InMemoryTaskRepository
from app.schemas.recommendations import RecommendationRequest
from app.services.recommender import RecommendationService
from tests.fake_semantics import requirement_analysis
from tests.test_langgraph_behaviors import FakeRagRetriever


class FakeSearchClient:
    def search_hardware(self, profile, query=None):
        return {
            "status": "success",
            "provider": "serpapi",
            "query": query or "fake query",
            "result_count": 1,
            "latency_ms": 1,
            "results": [
                {
                    "title": "hardware evidence",
                    "link": "https://example.com/item",
                    "source": "fake",
                    "price": "1000",
                }
            ],
            "error": None,
        }


class SixRoleFakeBrain:
    def __init__(self, failing_role=None):
        self.calls = []
        self.failing_role = failing_role

    def invoke_agent(self, agent_name, payload, response_model):
        self.calls.append(agent_name)
        if agent_name == self.failing_role:
            return {
                "status": "failed",
                "provider": "deepseek",
                "model": "fake-deepseek",
                "latency_ms": 1,
                "usage": {"input_tokens": 3, "output_tokens": 0, "total_tokens": 3},
                "result": {},
                "error": "simulated model failure",
            }

        result = {
            "summary": f"{agent_name} AI completed",
            "observations": [],
            "questions": [],
            "query": "2万元 3A 游戏 CPU GPU 实时价格",
            "rationale": ["六个 AI 节点均已完成分析。"],
            "alternatives": [],
            "risks": [],
        }
        if agent_name == "IntentClassificationAgent":
            result = {
                "is_pc_build_request": True,
                "request_type": "pc_build",
                "confidence": 0.99,
                "reason": "PC build request",
            }
        elif agent_name == "RequirementAgent":
            result = requirement_analysis(payload["user_text"])
        elif agent_name == "HardwareSelectionAgent":
            result["parts"] = self._parts()
        return {
            "status": "success",
            "provider": "deepseek",
            "model": "fake-deepseek",
            "latency_ms": 1,
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            "result": result,
            "error": None,
        }

    @staticmethod
    def _parts():
        return [
            {"id": "cpu", "category": "cpu", "name": "CPU", "price": 3000, "specs": {"socket": "AM5", "tdp": 120}},
            {"id": "gpu", "category": "gpu", "name": "GPU", "price": 11000, "specs": {"length_mm": 330, "tdp": 360}},
            {"id": "mb", "category": "motherboard", "name": "Board", "price": 2000, "specs": {"socket": "AM5", "memory_type": "DDR5", "form_factor": "ATX"}},
            {"id": "ram", "category": "memory", "name": "Memory", "price": 1200, "specs": {"memory_type": "DDR5", "capacity_gb": 64}},
            {"id": "ssd", "category": "storage", "name": "SSD", "price": 1200, "specs": {"capacity_gb": 4000}},
            {"id": "psu", "category": "psu", "name": "PSU", "price": 900, "specs": {"watt": 1000}},
            {"id": "cooler", "category": "cooler", "name": "Cooler", "price": 500, "specs": {"height_mm": 155, "tdp": 300}},
            {"id": "case", "category": "case", "name": "Case", "price": 700, "specs": {"max_gpu_length_mm": 400, "max_cooler_height_mm": 170, "form_factor": "ATX"}},
        ]


class SixAgentAiBrainTests(unittest.TestCase):
    def make_service(self, brain):
        return RecommendationService(
            InMemoryCatalogRepository(),
            InMemoryTaskRepository(),
            search_client=FakeSearchClient(),
            llm_client=brain,
            rag_retriever=FakeRagRetriever(),
        )

    def run_task(self, brain):
        service = self.make_service(brain)
        created = service.create_task(
            RecommendationRequest(text="给我配一台2w-3w的纯游戏主机，要求流畅游玩所有3A大作")
        )
        service.run_task(created["task_id"])
        return service.tasks.get(created["task_id"])

    def test_successful_build_calls_deepseek_for_all_eight_agents(self):
        brain = SixRoleFakeBrain()
        task = self.run_task(brain)

        self.assertEqual(task["status"], "completed")
        expected_calls = [
            AGENT_NAMES[0],
            AGENT_NAMES[1],
            AGENT_NAMES[2],
            AGENT_NAMES[2],
            AGENT_NAMES[3],
            AGENT_NAMES[4],
            AGENT_NAMES[5],
            AGENT_NAMES[6],
            AGENT_NAMES[6],
            AGENT_NAMES[7],
        ]
        self.assertEqual(brain.calls, expected_calls)
        self.assertEqual(task["result"]["ai_usage"]["total_tokens"], 150)
        self.assertTrue(all(run["ai_call"]["status"] == "success" for run in task["agent_runs"]))

    def test_budget_agent_records_planning_tool_and_reflection_events(self):
        brain = SixRoleFakeBrain()
        task = self.run_task(brain)
        budget_run = next(run for run in task["agent_runs"] if run["agent_name"] == "BudgetParsingAgent")

        phases = [event["phase"] for event in budget_run["events"]]
        self.assertEqual(phases, ["plan", "tool", "reflection"])
        self.assertIn("parse_budget_constraint", budget_run["tool_calls"])

    def test_compatibility_agent_runs_ai_plan_tools_and_reflection(self):
        task = self.run_task(SixRoleFakeBrain())
        run = next(
            item
            for item in task["agent_runs"]
            if item["agent_name"] == "CompatibilityAndPricingAgent"
        )

        self.assertEqual(
            [event["phase"] for event in run["events"]],
            ["plan", "tool", "reflection"],
        )
        self.assertEqual(len(run["ai_calls"]), 2)

    def test_required_ai_failure_never_publishes_local_fallback(self):
        brain = SixRoleFakeBrain(failing_role="RequirementAgent")
        task = self.run_task(brain)

        self.assertEqual(task["status"], "degraded")
        self.assertEqual(task["result"]["parts"], [])
        self.assertEqual(task["result"]["provenance"]["build_source"], "none")
        self.assertIn("RequirementAgent", task["degraded_reason"])


    def test_optional_ai_questions_do_not_block_complete_requirement(self):
        brain = SixRoleFakeBrain()
        original = brain.invoke_agent

        def noisy_requirement(agent_name, payload, response_model):
            response = original(agent_name, payload, response_model)
            if agent_name == "RequirementAgent":
                response["result"]["questions"] = ["是否开启光追？", "是否追求静音？"]
            return response

        brain.invoke_agent = noisy_requirement
        task = self.run_task(brain)

        self.assertEqual(task["status"], "completed")
        expected_calls = [
            AGENT_NAMES[0],
            AGENT_NAMES[1],
            AGENT_NAMES[2],
            AGENT_NAMES[2],
            AGENT_NAMES[3],
            AGENT_NAMES[4],
            AGENT_NAMES[5],
            AGENT_NAMES[6],
            AGENT_NAMES[6],
            AGENT_NAMES[7],
        ]
        self.assertEqual(brain.calls, expected_calls)
    def test_hardware_normalization_maps_common_ai_spec_aliases(self):
        parts = HardwareSelectionAgent.normalize(
            [
                {"category": "psu", "name": "PSU", "price": 1000, "specs": {"wattage": 1000}},
                {"category": "gpu", "name": "GPU", "price": 9000, "specs": {"power_w": 360, "length": 330}},
                {"category": "case", "name": "Case", "price": 800, "specs": {"gpu_clearance_mm": 400, "cooler_clearance_mm": 175}},
            ]
        )

        self.assertEqual(parts[0]["specs"]["watt"], 1000)
        self.assertEqual(parts[1]["specs"]["tdp"], 360)
        self.assertEqual(parts[1]["specs"]["length_mm"], 330)
        self.assertEqual(parts[2]["specs"]["max_gpu_length_mm"], 400)
        self.assertEqual(parts[2]["specs"]["max_cooler_height_mm"], 175)
if __name__ == "__main__":
    unittest.main()
