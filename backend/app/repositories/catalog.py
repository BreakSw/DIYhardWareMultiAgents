from __future__ import annotations

from typing import Protocol


class CatalogRepository(Protocol):
    def list_parts(self, category: str | None = None) -> list[dict]: ...


class InMemoryCatalogRepository:
    """Demo catalog used until the MySQL catalog is populated."""

    def __init__(self) -> None:
        self._parts = [
            {"id": "cpu-7500f", "category": "cpu", "name": "AMD Ryzen 5 7500F", "price": 1199, "specs": {"socket": "AM5", "tdp": 65}},
            {"id": "cpu-13400f", "category": "cpu", "name": "Intel Core i5-13400F", "price": 1299, "specs": {"socket": "LGA1700", "tdp": 148}},
            {"id": "cpu-14600kf", "category": "cpu", "name": "Intel Core i5-14600KF", "price": 1899, "specs": {"socket": "LGA1700", "tdp": 181}},
            {"id": "gpu-4060", "category": "gpu", "name": "NVIDIA GeForce RTX 4060 8GB", "price": 2199, "specs": {"length_mm": 245, "tdp": 115, "tier": "1080p-2k"}},
            {"id": "gpu-4060ti", "category": "gpu", "name": "NVIDIA GeForce RTX 4060 Ti 16GB", "price": 3199, "specs": {"length_mm": 305, "tdp": 165, "tier": "2k"}},
            {"id": "gpu-6750gre", "category": "gpu", "name": "AMD Radeon RX 6750 GRE 12GB", "price": 2399, "specs": {"length_mm": 280, "tdp": 230, "tier": "2k"}},
            {"id": "mb-b650", "category": "motherboard", "name": "微星 PRO B650M-A WIFI", "price": 999, "specs": {"socket": "AM5", "memory_type": "DDR5", "form_factor": "mATX"}},
            {"id": "mb-b760", "category": "motherboard", "name": "华硕 TUF GAMING B760M-PLUS WIFI", "price": 1099, "specs": {"socket": "LGA1700", "memory_type": "DDR5", "form_factor": "mATX"}},
            {"id": "ram-ddr5", "category": "memory", "name": "光威 天策 DDR5 6000 16GB x2", "price": 699, "specs": {"memory_type": "DDR5", "capacity_gb": 32}},
            {"id": "ssd-1tb", "category": "storage", "name": "致态 TiPlus7100 1TB", "price": 549, "specs": {"capacity_gb": 1000, "interface": "NVMe"}},
            {"id": "psu-650", "category": "psu", "name": "海韵 CORE GX 650W", "price": 599, "specs": {"watt": 650}},
            {"id": "psu-750", "category": "psu", "name": "安钛克 NE750 GOLD 750W", "price": 699, "specs": {"watt": 750}},
            {"id": "cooler-ak400", "category": "cooler", "name": "利民 AK400", "price": 129, "specs": {"height_mm": 155, "tdp": 220}},
            {"id": "cooler-pa120", "category": "cooler", "name": "利民 PA120 SE", "price": 189, "specs": {"height_mm": 157, "tdp": 265}},
            {"id": "case-matx", "category": "case", "name": "乔思伯 D31 Mesh", "price": 399, "specs": {"max_gpu_length_mm": 400, "max_cooler_height_mm": 168, "form_factor": "mATX"}},
        ]

    def list_parts(self, category: str | None = None) -> list[dict]:
        if category is None:
            return list(self._parts)
        return [part for part in self._parts if part["category"] == category]


class InMemoryTaskRepository:
    def __init__(self) -> None:
        self.tasks: dict[str, dict] = {}
        self.traces: dict[str, list[dict]] = {}

    def save(self, task_id: str, payload: dict) -> None:
        self.tasks[task_id] = payload

    def get(self, task_id: str) -> dict | None:
        return self.tasks.get(task_id)

    def add_trace(self, task_id: str, event: dict) -> None:
        self.traces.setdefault(task_id, []).append(event)

    def get_trace(self, task_id: str) -> list[dict]:
        return self.traces.get(task_id, [])
