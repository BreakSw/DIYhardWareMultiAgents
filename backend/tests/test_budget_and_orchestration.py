from __future__ import annotations

import unittest

from app.agents.state import AGENT_NAMES
from app.repositories.catalog import InMemoryCatalogRepository, InMemoryTaskRepository
from app.schemas.recommendations import RecommendationRequest
from app.services.recommender import RecommendationService
from app.services.requirement_parser import RequirementParser
from tests.fake_semantics import requirement_analysis


class FakeSearchClient:
    def search_hardware(self, profile, query=None):
        return {
            "status": "success",
            "provider": "serpapi",
            "query": "test",
            "result_count": 1,
            "latency_ms": 1,
            "results": [{"title": "test", "link": "https://example.com", "source": "test"}],
            "error": None,
        }


class FakeRagRetriever:
    def retrieve(self, query, *, top_k=None):
        return {
            "status": "success",
            "provider": "local-rag",
            "retrieval_mode": "vector",
            "result_count": 1,
            "catalog_count": 80,
            "results": [
                {"title": "test", "link": "https://example.com/rag", "source": "local-rag:verified", "price": "1000"}
            ],
            "error": None,
        }


def invalid_parts():
    return [
        {"id": "cpu", "category": "cpu", "name": "CPU", "price": 1000, "specs": {"socket": "AM5", "tdp": 120}},
        {"id": "gpu", "category": "gpu", "name": "GPU", "price": 1000, "specs": {"length_mm": 300, "tdp": 300}},
        {"id": "mb", "category": "motherboard", "name": "Board", "price": 800, "specs": {"socket": "AM5", "memory_type": "DDR5", "form_factor": "ATX"}},
        {"id": "ram", "category": "memory", "name": "RAM", "price": 500, "specs": {"memory_type": "DDR5", "capacity_gb": 64}},
        {"id": "ssd", "category": "storage", "name": "SSD", "price": 500, "specs": {"capacity_gb": 4000}},
        {"id": "psu", "category": "psu", "name": "PSU", "price": 700, "specs": {"watt": 1000}},
        {"id": "cooler", "category": "cooler", "name": "Cooler", "price": 200, "specs": {"height_mm": 155, "tdp": 250}},
        {"id": "case", "category": "case", "name": "Case", "price": 300, "specs": {"max_gpu_length_mm": 400, "max_cooler_height_mm": 170, "form_factor": "ATX"}},
    ]


class AlwaysInvalidBrain:
    def __init__(self):
        self.hardware_calls = 0

    def invoke_agent(self, agent_name, payload, response_model):
        result = {
            "summary": f"{agent_name} completed",
            "observations": [],
            "questions": [],
            "query": "fake query",
            "rationale": ["fake report"],
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
            self.hardware_calls += 1
            result["parts"] = invalid_parts()
        return {
            "status": "success",
            "provider": "deepseek",
            "model": "fake",
            "latency_ms": 1,
            "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            "error": None,
            "result": result,
        }


class BudgetParserTests(unittest.TestCase):
    def setUp(self):
        self.parser = RequirementParser()

    def test_chinese_budget_range(self):
        profile = self.parser.parse("预算四万到五万，主要玩4K 3A游戏")
        self.assertEqual((profile.budget_min, profile.budget_max, profile.budget), (40000, 50000, 45000))

    def test_existing_budget_formats(self):
        cases = {
            "预算2w-3w玩3A": (20000, 30000, 25000),
            "预算2万元玩2K": (20000, 20000, 20000),
            "预算8000到12000元做剪辑": (8000, 12000, 10000),
        }
        for text, expected in cases.items():
            profile = self.parser.parse(text)
            self.assertEqual((profile.budget_min, profile.budget_max, profile.budget), expected)

    def test_lower_bound_budget_has_no_invented_ceiling(self):
        profile = self.parser.parse("我想配一台5w以上的电脑，配置要多好有多好")

        self.assertTrue(profile.budget_explicit)
        self.assertEqual(profile.budget_mode, "lower_bound")
        self.assertEqual(profile.budget_min, 50000)
        self.assertIsNone(profile.budget_max)
        self.assertEqual(profile.budget, 50000)
        self.assertEqual(profile.budget_evidence, "5w以上")

    def test_budget_parser_does_not_guess_semantic_requirements(self):
        profile = self.parser.parse(
            "我想配一台5000元左右的主机，主要玩《英雄联盟》和《无畏契约》"
        )

        self.assertFalse(profile.usage_explicit)
        self.assertEqual(profile.usage, "pending AI analysis")


class OrchestrationTests(unittest.TestCase):
    def make_service(self, brain):
        return RecommendationService(
            InMemoryCatalogRepository(),
            InMemoryTaskRepository(),
            search_client=FakeSearchClient(),
            llm_client=brain,
            rag_retriever=FakeRagRetriever(),
        )

    def test_out_of_budget_model_retries_then_degrades_without_fallback(self):
        brain = AlwaysInvalidBrain()
        service = self.make_service(brain)
        task = service.create_task(
            RecommendationRequest(text="预算四万到五万，主要玩4K 3A游戏，只要主机")
        )
        service.run_task(task["task_id"])
        saved = service.tasks.get(task["task_id"])

        self.assertEqual(brain.hardware_calls, 2)
        self.assertEqual(saved["status"], "degraded")
        self.assertEqual(saved["result"]["parts"], [])
        self.assertFalse(saved["result"]["budget_check"]["passed"])
        self.assertEqual([run["agent_name"] for run in saved["agent_runs"]], AGENT_NAMES)

    def test_missing_usage_needs_clarification_after_requirement_ai(self):
        service = self.make_service(AlwaysInvalidBrain())
        task = service.create_task(RecommendationRequest(text="预算四万到五万，给我配一台电脑"))
        service.run_task(task["task_id"])
        saved = service.tasks.get(task["task_id"])

        self.assertEqual(saved["status"], "needs_clarification")
        self.assertTrue(saved["follow_up_questions"])
        self.assertEqual(saved["agent_runs"][0]["ai_call"]["status"], "success")
        self.assertEqual(saved["agent_runs"][1]["ai_call"]["status"], "success")


if __name__ == "__main__":
    unittest.main()
