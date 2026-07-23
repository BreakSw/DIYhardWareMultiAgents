from __future__ import annotations

class CompatibilityService:
    def check(self, parts: list[dict]) -> list[dict]:
        by_category = {part.get("category"): part for part in parts}
        cpu = by_category.get("cpu", {}).get("specs", {})
        motherboard = by_category.get("motherboard", {}).get("specs", {})
        gpu = by_category.get("gpu", {}).get("specs", {})
        memory = by_category.get("memory", {}).get("specs", {})
        case = by_category.get("case", {}).get("specs", {})
        cooler = by_category.get("cooler", {}).get("specs", {})
        psu = by_category.get("psu", {}).get("specs", {})
        checks: list[dict] = []

        def add(name: str, passed: bool, detail: str, severity: str = "error") -> None:
            checks.append({"name": name, "passed": passed, "severity": "success" if passed else severity, "detail": detail})

        add("CPU 与主板插槽", cpu.get("socket") == motherboard.get("socket"), f"{cpu.get('socket', '未知')} / {motherboard.get('socket', '未知')}")
        add("内存类型", memory.get("memory_type") == motherboard.get("memory_type"), f"{memory.get('memory_type', '未知')} / {motherboard.get('memory_type', '未知')}")
        add("显卡长度", gpu.get("length_mm", 0) <= case.get("max_gpu_length_mm", 0), f"{gpu.get('length_mm', 0)}mm / {case.get('max_gpu_length_mm', 0)}mm")
        add("散热器高度", cooler.get("height_mm", 0) <= case.get("max_cooler_height_mm", 0), f"{cooler.get('height_mm', 0)}mm / {case.get('max_cooler_height_mm', 0)}mm")
        estimated_power = cpu.get("tdp", 0) + gpu.get("tdp", 0) + 180
        safe_power = int(psu.get("watt", 0) * 0.75)
        add("电源余量", estimated_power <= safe_power, f"预计 {estimated_power}W / 建议安全上限 {safe_power}W", "warning")
        return checks
