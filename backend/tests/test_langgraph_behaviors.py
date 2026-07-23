from __future__ import annotations

import unittest

from app.agents.orchestration import AGENT_NAMES
from app.repositories.catalog import InMemoryCatalogRepository, InMemoryTaskRepository
from app.schemas.recommendations import RecommendationRequest
from app.services.recommender import RecommendationService
from tests.test_twenty_requirements import PROMPTS
from tests.fake_semantics import requirement_analysis


class FakeSearchClient:
    def search_hardware(self, profile, query=None):
        return {
            "status": "success",
            "provider": "serpapi",
            "query": "fake query",
            "result_count": 2,
            "latency_ms": 1,
            "results": [
                {"title": "CPU price", "link": "https://example.com/cpu", "source": "fake", "price": "1000"},
                {"title": "GPU price", "link": "https://example.com/gpu", "source": "fake", "price": "2000"},
            ],
            "error": None,
        }


class DisabledSearchClient:
    is_configured = False

    def search_hardware(self, profile, query=None):
        raise AssertionError("disabled search tool must not be called")


class FakeRagRetriever:
    def retrieve(self, query, *, top_k=None):
        return {
            "status": "success",
            "provider": "local-rag",
            "retrieval_mode": "vector",
            "result_count": 2,
            "catalog_count": 80,
            "results": [
                {"title": "RAG CPU", "link": "https://example.com/rag-cpu", "source": "local-rag:verified", "price": "1000", "category": "cpu"},
                {"title": "RAG GPU", "link": "https://example.com/rag-gpu", "source": "local-rag:verified", "price": "2000", "category": "gpu"},
            ],
            "error": None,
        }


class BudgetAwareFakeLlm:
    def __init__(self) -> None:
        self.calls = 0

    def invoke_agent(self, agent_name, payload, response_model):
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
            from app.schemas.recommendations import RequirementProfile

            profile = RequirementProfile.model_validate(payload["profile"])
            self.calls += 1
            target = profile.budget_min - 1000 if profile.allow_under_budget and profile.budget_min > 10000 else profile.budget
            result = {
                "parts": self._parts(profile, target),
                "rationale": ["fake evidence-backed plan"],
                "alternatives": [],
            }
        else:
            result = {
                "summary": f"{agent_name} completed",
                "observations": [],
                "questions": [],
                "query": "fake query",
                "rationale": ["fake report"],
                "alternatives": [],
                "risks": [],
            }
        return {
            "status": "success",
            "provider": "deepseek",
            "model": "fake-structured",
            "latency_ms": 1,
            "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            "error": None,
            "result": result,
        }
    def generate_build(self, user_text, profile, search, revision_feedback=None):
        self.calls += 1
        target = profile.budget_min - 1000 if profile.allow_under_budget and profile.budget_min > 10000 else profile.budget
        parts = self._parts(profile, target)
        return {
            "status": "success",
            "provider": "deepseek",
            "model": "fake-structured",
            "latency_ms": 1,
            "usage": {},
            "error": None,
            "result": {
                "parts": parts,
                "rationale": ["fake evidence-backed plan"],
                "alternatives": [],
            },
        }

    @staticmethod
    def _parts(profile, target):
        parts = [
            {"id": "cpu", "category": "cpu", "name": "AMD CPU", "price": 1000, "specs": {"socket": "AM5", "tdp": 105}},
            {"id": "mb", "category": "motherboard", "name": "AM5 Board", "price": 800, "specs": {"socket": "AM5", "memory_type": "DDR5", "form_factor": "ATX"}},
            {"id": "ram", "category": "memory", "name": "DDR5 Memory", "price": 500, "specs": {"memory_type": "DDR5", "capacity_gb": 64}},
            {"id": "ssd", "category": "storage", "name": "NVMe SSD", "price": 500, "specs": {"capacity_gb": 4000}},
            {"id": "psu", "category": "psu", "name": "1000W PSU", "price": 700, "specs": {"watt": 1000}},
            {"id": "cooler", "category": "cooler", "name": "Air Cooler", "price": 200, "specs": {"height_mm": 155, "tdp": 250}},
            {"id": "case", "category": "case", "name": "ATX Case", "price": 300, "specs": {"max_gpu_length_mm": 400, "max_cooler_height_mm": 170, "form_factor": "ATX"}},
        ]
        if profile.include_peripherals:
            parts.extend(
                [
                    {"id": "monitor", "category": "monitor", "name": "Display", "price": 1000, "specs": {}},
                    {"id": "keyboard", "category": "keyboard", "name": "Keyboard", "price": 300, "specs": {}},
                    {"id": "mouse", "category": "mouse", "name": "Mouse", "price": 200, "specs": {}},
                ]
            )
        current = sum(part["price"] for part in parts)
        if "gpu" in profile.owned_parts:
            parts[0]["price"] += target - current
        else:
            parts.append(
                {
                    "id": "gpu",
                    "category": "gpu",
                    "name": "NVIDIA GPU",
                    "price": target - current,
                    "specs": {"length_mm": 300, "tdp": 300},
                }
            )
        return parts


class LangGraphBehaviorTests(unittest.TestCase):
    def make_service(self):
        llm = BudgetAwareFakeLlm()
        service = RecommendationService(
            InMemoryCatalogRepository(),
            InMemoryTaskRepository(),
            search_client=FakeSearchClient(),
            llm_client=llm,
            rag_retriever=FakeRagRetriever(),
        )
        return service, llm

    def run_prompt(self, prompt):
        service, llm = self.make_service()
        created = service.create_task(RecommendationRequest(text=prompt))
        service.run_task(created["task_id"])
        return service.tasks.get(created["task_id"]), service, llm

    def test_graph_registers_exactly_eight_business_nodes(self):
        service, _ = self.make_service()
        graph_nodes = set(service.graph.get_graph().nodes)
        self.assertEqual(graph_nodes.intersection(AGENT_NAMES), set(AGENT_NAMES))
        self.assertEqual(len(graph_nodes.intersection(AGENT_NAMES)), 8)

    def test_priority_budget_prompts_publish_in_range(self):
        for index in [5, 7]:
            task, _, _ = self.run_prompt(PROMPTS[index])
            result = task["result"]
            self.assertEqual(task["status"], "completed", PROMPTS[index])
            self.assertTrue(result["budget_check"]["passed"])
            self.assertGreaterEqual(result["total_price"], result["profile"]["budget_min"])
            self.assertLessEqual(result["total_price"], result["profile"]["budget_max"])
            self.assertEqual(len(result["agent_runs"]), 8)

    def test_lower_bound_budget_can_complete_without_an_invented_ceiling(self):
        task, _, _ = self.run_prompt(
            "我想配一台5w以上的电脑，主要玩所有3A游戏，只要主机"
        )

        self.assertEqual(task["status"], "completed")
        self.assertIsNone(task["result"]["profile"]["budget_max"])
        self.assertGreaterEqual(task["result"]["total_price"], 50000)
        self.assertTrue(task["result"]["budget_check"]["passed"])

    def test_disabled_search_skips_only_search_and_continues_build(self):
        service = RecommendationService(
            InMemoryCatalogRepository(),
            InMemoryTaskRepository(),
            search_client=DisabledSearchClient(),
            llm_client=BudgetAwareFakeLlm(),
            rag_retriever=FakeRagRetriever(),
        )
        created = service.create_task(
            RecommendationRequest(
                text="预算6000到8000元，主要玩英雄联盟和无畏契约，只要主机"
            )
        )
        service.run_task(created["task_id"])
        task = service.tasks.get(created["task_id"])

        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["agent_runs"][4]["status"], "completed")
        self.assertTrue(all(run["status"] == "completed" for run in task["agent_runs"][5:]))

    def test_allow_under_budget_is_explicit_and_explained(self):
        for index in [8, 19]:
            task, _, _ = self.run_prompt(PROMPTS[index])
            result = task["result"]
            self.assertEqual(task["status"], "completed")
            self.assertTrue(result["profile"]["allow_under_budget"])
            self.assertTrue(result["budget_check"]["passed"])
            if result["total_price"] < result["profile"]["budget_min"]:
                self.assertTrue(any("不花满" in line for line in result["rationale"]))

    def test_owned_gpu_requires_usage_then_is_not_purchased_again(self):
        clarification, _, _ = self.run_prompt(PROMPTS[12])
        self.assertEqual(clarification["status"], "needs_clarification")

        service, _ = self.make_service()
        created = service.create_task(RecommendationRequest(text=PROMPTS[12], usage="游戏"))
        service.run_task(created["task_id"])
        task = service.tasks.get(created["task_id"])
        result = task["result"]
        purchased_gpu = [part for part in result["parts"] if part["category"] == "gpu"]
        self.assertEqual(task["status"], "completed")
        self.assertEqual(purchased_gpu, [])
        self.assertEqual(result["profile"]["owned_parts"]["gpu"], "RTX 4070")

    def test_ambiguous_prompt_needs_clarification_without_tools(self):
        task, _, llm = self.run_prompt(PROMPTS[16])
        self.assertEqual(task["status"], "needs_clarification")
        self.assertTrue(task["follow_up_questions"])
        self.assertEqual(llm.calls, 0)
        self.assertEqual(len(task["agent_runs"]), 8)
        self.assertEqual(task["agent_runs"][3]["status"], "completed")
        self.assertTrue(all(run["status"] == "skipped" for run in task["agent_runs"][4:]))

    def test_impossible_prompt_degrades_without_fake_build(self):
        task, _, llm = self.run_prompt(PROMPTS[17])
        result = task["result"]
        self.assertEqual(task["status"], "degraded")
        self.assertLessEqual(result["score"], 60)
        self.assertEqual(result["parts"], [])
        self.assertFalse(result["budget_check"]["passed"])
        self.assertEqual(llm.calls, 0)
        self.assertEqual(task["agent_runs"][-1]["status"], "skipped")


if __name__ == "__main__":
    unittest.main()
