from __future__ import annotations

from typing import Any

from app.repositories.catalog import CatalogRepository
from app.schemas.recommendations import RecommendationRequest, RequirementProfile
from app.services.llm_client import BuildPlan


class HardwareSelectionAgent:
    name = "HardwareSelectionAgent"

    def __init__(self, brain: Any, catalog: CatalogRepository) -> None:
        self.brain = brain
        self.catalog = catalog

    def run(
        self,
        request: RecommendationRequest,
        profile: RequirementProfile,
        search_result: dict[str, Any],
        revision_feedback: str | None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
        response = self.brain.invoke_agent(
            self.name,
            {
                "task": (
                    "根据结构化需求和搜索证据生成完整采购清单。总价必须在预算区间内；"
                    "不得重复购买已有部件。specs 必须使用以下精确字段："
                    "CPU socket/tdp；GPU length_mm/tdp；"
                    "motherboard socket/memory_type/form_factor；"
                    "memory memory_type/capacity_gb；PSU watt；"
                    "cooler height_mm/tdp；case max_gpu_length_mm/"
                    "max_cooler_height_mm/form_factor。数值字段只能输出数字。"
                ),
                "user_text": request.text,
                "profile": profile.model_dump(),
                "search_evidence": search_result.get("results", [])[:12],
                "revision_feedback": revision_feedback,
                "required_categories": self._required_categories(profile),
            },
            BuildPlan,
        )
        payload = response.get("result", {})
        raw_parts = payload.get("parts", [])
        parts = (
            self.normalize(raw_parts)
            if response.get("status") == "success" and isinstance(raw_parts, list)
            else []
        )
        if "gpu" in profile.owned_parts:
            parts = [part for part in parts if part["category"] != "gpu"]
        return parts, payload, response

    @staticmethod
    def _required_categories(profile: RequirementProfile) -> list[str]:
        categories = ["cpu", "motherboard", "memory", "storage", "psu", "cooler", "case"]
        if "gpu" not in profile.owned_parts:
            categories.insert(1, "gpu")
        if profile.include_peripherals:
            categories.extend(["monitor", "keyboard", "mouse"])
        return categories

    @staticmethod
    def normalize(parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for index, part in enumerate(parts):
            category = str(part.get("category", "other")).lower()
            specs = part.get("specs") if isinstance(part.get("specs"), dict) else {}
            specs = dict(specs)
            HardwareSelectionAgent._map_spec_aliases(category, specs)
            normalized.append(
                {
                    "id": str(part.get("id") or f"{category}-{index}"),
                    "category": category,
                    "name": str(part.get("name") or "未命名部件"),
                    "price": max(0, int(part.get("price") or 0)),
                    "specs": specs,
                }
            )
        return normalized

    @staticmethod
    def _map_spec_aliases(category: str, specs: dict[str, Any]) -> None:
        aliases = {
            "psu": {"watt": ["wattage", "power_w", "power", "capacity_w"]},
            "cpu": {"tdp": ["power_w", "wattage", "power"]},
            "gpu": {
                "tdp": ["power_w", "wattage", "power", "tbp"],
                "length_mm": ["length", "gpu_length_mm"],
            },
            "cooler": {
                "height_mm": ["height", "cooler_height_mm"],
                "tdp": ["cooling_tdp", "power_w"],
            },
            "case": {
                "max_gpu_length_mm": ["gpu_clearance_mm", "max_gpu_length", "gpu_length_mm"],
                "max_cooler_height_mm": [
                    "cooler_clearance_mm",
                    "max_cooler_height",
                    "cooler_height_mm",
                ],
            },
            "memory": {"memory_type": ["type", "ram_type"]},
            "motherboard": {"memory_type": ["ram_type", "memory"]},
        }
        for canonical, candidates in aliases.get(category, {}).items():
            if specs.get(canonical) not in (None, ""):
                continue
            for candidate in candidates:
                if specs.get(candidate) not in (None, ""):
                    specs[canonical] = specs[candidate]
                    break
