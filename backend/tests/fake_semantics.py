from __future__ import annotations

import re


def requirement_analysis(text: str) -> dict:
    """Predictable semantic output for tests; production uses DeepSeek."""
    normalized = text.lower()
    usage_markers = [
        "游戏", "网游", "3a", "英雄联盟", "无畏契约", "剪辑", "渲染",
        "训练", "办公", "编程", "直播", "blender", "虚幻引擎",
    ]
    game = any(word in normalized for word in ["游戏", "网游", "3a", "英雄联盟", "无畏契约"])
    work = any(word in normalized for word in ["剪辑", "渲染", "训练", "办公", "编程", "直播", "blender", "虚幻引擎"])
    explicit = any(word in normalized for word in usage_markers)
    usage = "游戏与生产力" if game and work else "游戏" if game else "生产力" if work else "综合使用"
    includes = any(word in text for word in ["包含显示器", "显示器都要", "键盘和鼠标", "包含外设"])
    excludes = any(word in text for word in ["只要主机", "不要外设", "不需要显示器"])
    owned = {}
    match = re.search(r"((?:RTX|GTX|RX)\s*\d{3,4}(?:\s*(?:Ti|SUPER))?)", text, re.IGNORECASE)
    if match and any(word in text for word in ["已经有", "已有", "我有"]):
        owned["gpu"] = match.group(1)
    impossible = None
    if "3000" in text and "4K" in text and includes:
        impossible = "该预算和性能范围不可实现"
    return {
        "summary": "fake semantic analysis",
        "usage": usage,
        "usage_explicit": explicit,
        "resolution": "4K" if "4k" in normalized else "1080p" if "1080" in normalized else "2K",
        "case_size": "ITX" if "itx" in normalized or "不能太大" in text else "ATX",
        "include_peripherals": includes and not excludes,
        "peripherals_explicit": includes or excludes,
        "allow_under_budget": any(
            marker in text
            for marker in [
                "不必花满",
                "不必强行花满",
                "不用花满",
                "最多",
                "以内",
                "能省则省",
            ]
        ),
        "owned_parts": owned,
        "constraints": [],
        "assumptions": [],
        "needs_clarification": not explicit,
        "missing_fields": [] if explicit else ["usage"],
        "questions": [] if explicit else ["请说明主要用途"],
        "impossible_reason": impossible,
        "confidence": 0.95,
    }
