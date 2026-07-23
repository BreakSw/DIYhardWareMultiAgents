from __future__ import annotations

import re

from app.schemas.recommendations import RequirementProfile


class RequirementParser:
    """Deterministic parsing for hard constraints that an LLM may not override."""

    _CN_DIGITS = "\u96f6\u3007\u4e00\u4e8c\u4e24\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\u767e"
    _TOKEN = rf"(?:\d+(?:\.\d+)?|[{_CN_DIGITS}]+)"
    _UNIT = r"(?:[wW\u4e07kK\u5343])?"
    _RANGE_SEP = r"(?:-|~|\uff5e|\u2014|\u2013|\u81f3|\u5230)"
    _DIGITS = {
        "\u96f6": 0, "\u3007": 0, "\u4e00": 1, "\u4e8c": 2,
        "\u4e24": 2, "\u4e09": 3, "\u56db": 4, "\u4e94": 5,
        "\u516d": 6, "\u4e03": 7, "\u516b": 8, "\u4e5d": 9,
    }

    def parse(self, text: str) -> RequirementProfile:
        budget_min, budget_max, explicit, mode, evidence = self.parse_budget_constraint(text)
        budget = budget_min if budget_max is None else (budget_min + budget_max) // 2
        notes: list[str] = []
        if mode == "range":
            notes.append(f"\u9884\u7b97\u533a\u95f4 {budget_min}-{budget_max} \u5143")
        elif mode == "lower_bound":
            notes.append(f"\u9884\u7b97\u4e0b\u9650 {budget_min} \u5143\uff0c\u7528\u6237\u672a\u8bbe\u7f6e\u4ef7\u683c\u4e0a\u9650")

        return RequirementProfile(
            budget=budget, budget_min=budget_min, budget_max=budget_max,
            budget_mode=mode, budget_evidence=evidence,
            usage="pending AI analysis", budget_explicit=explicit,
            usage_explicit=False, peripherals_explicit=False,
            assumptions=[], notes=notes,
        )

    def parse_budget_constraint(self, text: str) -> tuple[int, int | None, bool, str, str]:
        bounded = re.search(
            rf"(?:\u4e0d\u4f4e\u4e8e|\u81f3\u5c11)\s*(?P<low>{self._TOKEN})\s*(?P<low_unit>{self._UNIT})(?:\s*\u5143)?.{{0,18}}?(?:\u4e0d\u80fd\u8d85\u8fc7|\u4e0d\u8d85\u8fc7|\u81f3\u591a)\s*(?P<high>{self._TOKEN})\s*(?P<high_unit>{self._UNIT})",
            text, re.IGNORECASE,
        )
        if bounded:
            low = self._to_yuan(bounded.group("low"), bounded.group("low_unit") or bounded.group("high_unit"))
            high = self._to_yuan(bounded.group("high"), bounded.group("high_unit") or bounded.group("low_unit"))
            return min(low, high), max(low, high), True, "range", bounded.group(0)

        range_match = re.search(
            rf"(?P<low>{self._TOKEN})\s*(?P<low_unit>{self._UNIT})\s*{self._RANGE_SEP}\s*(?P<high>{self._TOKEN})\s*(?P<high_unit>{self._UNIT})",
            text,
        )
        if range_match:
            low = self._to_yuan(range_match.group("low"), range_match.group("low_unit") or range_match.group("high_unit"))
            high = self._to_yuan(range_match.group("high"), range_match.group("high_unit") or range_match.group("low_unit"))
            return min(low, high), max(low, high), True, "range", range_match.group(0)

        lower_bound = re.search(
            rf"(?:(?:\u9884\u7b97|\u4ef7\u4f4d|\u603b\u4ef7|\u4ef7\u683c)\s*)?(?P<value>{self._TOKEN})\s*(?P<unit>{self._UNIT})\s*(?:\u5143|\u5757)?\s*(?:\u4ee5\u4e0a|\u8d77\u6b65|\u5f80\u4e0a|\u53ca\u4ee5\u4e0a|\u4e0d\u5c11\u4e8e)",
            text, re.IGNORECASE,
        )
        if lower_bound:
            value = self._to_yuan(lower_bound.group("value"), lower_bound.group("unit"))
            return value, None, True, "lower_bound", lower_bound.group(0).strip()

        maximum = re.search(rf"(?:\u6700\u591a|\u6700\u9ad8(?:\u4e0d\u8d85\u8fc7)?|\u4e0d\u8d85\u8fc7)\s*(?P<value>{self._TOKEN})\s*(?P<unit>{self._UNIT})(?:\s*(?:\u5143|\u5757))?", text, re.IGNORECASE)
        contextual = re.search(rf"(?:\u9884\u7b97|\u4ef7\u4f4d|\u603b\u4ef7|\u4ef7\u683c)[^\d{self._CN_DIGITS}]{{0,8}}(?P<value>{self._TOKEN})\s*(?P<unit>{self._UNIT})(?:\s*(?:\u5143|\u5757))?", text, re.IGNORECASE)
        explicit_yuan = re.search(rf"(?P<value>{self._TOKEN})\s*(?P<unit>{self._UNIT})\s*(?:\u5143|\u5757)", text, re.IGNORECASE)
        match = maximum or contextual or explicit_yuan
        if match:
            value = self._to_yuan(match.group("value"), match.group("unit"))
            return value, value, True, "exact", match.group(0)
        return 6000, 6000, False, "unspecified", ""

    def _to_yuan(self, value: str, unit: str | None) -> int:
        number = float(value) if re.fullmatch(r"\d+(?:\.\d+)?", value) else float(self._chinese_number(value))
        multiplier = 10000 if unit in {"\u4e07", "w", "W"} else 1000 if unit in {"\u5343", "k", "K"} else 1
        return int(number * multiplier)

    def _chinese_number(self, value: str) -> int:
        if "\u767e" in value:
            left, _, right = value.partition("\u767e")
            return self._DIGITS.get(left, 1) * 100 + self._chinese_number(right or "\u96f6")
        if "\u5341" in value:
            left, _, right = value.partition("\u5341")
            return self._DIGITS.get(left, 1) * 10 + self._DIGITS.get(right, 0)
        return self._DIGITS.get(value, 0)
