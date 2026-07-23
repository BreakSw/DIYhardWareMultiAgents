from __future__ import annotations

from app.agents.requirement import RequirementAgent
from app.agents.search_knowledge import SearchAndKnowledgeAgent
from app.schemas.recommendations import RecommendationRequest
from app.services.requirement_parser import RequirementParser


def success(result):
    return {
        "status": "success",
        "provider": "deepseek",
        "model": "fake",
        "latency_ms": 1,
        "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
        "result": result,
        "error": None,
    }


class SemanticBrain:
    def invoke_agent(self, agent_name, payload, response_model):
        if agent_name == "RequirementAgent":
            return success(
                {
                    "summary": "An unfamiliar title is still clearly a game workload.",
                    "usage": "游戏",
                    "usage_explicit": True,
                    "resolution": "2K",
                    "case_size": "ATX",
                    "include_peripherals": False,
                    "peripherals_explicit": True,
                    "allow_under_budget": False,
                    "owned_parts": {},
                    "constraints": ["高帧率优先"],
                    "assumptions": [],
                    "needs_clarification": False,
                    "questions": [],
                    "impossible_reason": None,
                    "confidence": 0.96,
                }
            )
        return success({"summary": "search", "query": "AI_DYNAMIC_QUERY"})


class CapturingSearchClient:
    def __init__(self):
        self.query = None

    def search_hardware(self, profile, query=None):
        self.query = query
        return {
            "status": "success",
            "provider": "serpapi",
            "query": query,
            "result_count": 0,
            "latency_ms": 1,
            "results": [],
            "error": None,
        }


class CapturingRagRetriever:
    def __init__(self):
        self.query = None

    def retrieve(self, query, *, top_k=None):
        self.query = query
        return {
            "status": "success",
            "provider": "local-rag",
            "retrieval_mode": "vector",
            "result_count": 1,
            "catalog_count": 80,
            "results": [
                {
                    "title": "AI planned evidence",
                    "link": "https://example.com/rag",
                    "source": "local-rag:verified",
                    "price": "9000",
                }
            ],
            "error": None,
        }


def test_requirement_agent_uses_ai_semantics_without_a_title_whitelist():
    parser = RequirementParser()
    request = RecommendationRequest(
        text="预算9000元，主要玩从未写进代码的新游戏《量子远征X》，只要主机"
    )
    profile = parser.parse(request.text)

    profile, questions, _ = RequirementAgent(parser, SemanticBrain()).run(request, profile)

    assert profile.usage == "游戏"
    assert profile.usage_explicit is True
    assert questions == []
    assert "高帧率优先" in profile.notes


def test_search_agent_executes_the_rag_query_planned_by_ai():
    parser = RequirementParser()
    profile = parser.parse("预算9000元")
    client = CapturingSearchClient()
    retriever = CapturingRagRetriever()

    result, _ = SearchAndKnowledgeAgent(client, SemanticBrain(), retriever).run(profile)

    assert retriever.query == "AI_DYNAMIC_QUERY"
    assert client.query is None
    assert result["query"] == "AI_DYNAMIC_QUERY"
