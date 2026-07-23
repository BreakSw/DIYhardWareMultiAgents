from __future__ import annotations

import unittest

from app.services.requirement_parser import RequirementParser


PROMPTS = [
    "我想配一台 5000 元左右的主机，主要玩《英雄联盟》和《无畏契约》，不需要显示器。",
    "预算 6000 到 8000 元，主要玩 2K 分辨率的 3A 游戏，希望以后方便升级。",
    "8000 元预算，用于 4K 游戏和视频剪辑，优先显卡与 32GB 内存。",
    "我要一台预算 1 万到 1.2 万元的电脑，主要玩大型单机游戏，要求高画质稳定 60 帧。",
    "预算一万五以内，主机和显示器都要，主要用于 2K 游戏与日常办公。",
    "我准备花 2w-3w 配一台纯游戏主机，希望能流畅运行目前所有 3A 大作。",
    "预算两万元左右，用于直播、视频剪辑和游戏，不要任何外设。",
    "我的预算是四万到五万元，主要进行 4K 视频剪辑、三维渲染和 AI 模型训练。",
    "最多 7000 元，不必花满，主要用于编程、办公和偶尔玩网游。",
    "预算不低于 9000 元且不能超过 11000 元，要求白色海景房机箱和水冷散热。",
    "预算 12000 元，只要主机，必须使用 AMD 处理器和 NVIDIA 显卡。",
    "我有一台 4K 144Hz 显示器，预算 18000 到 22000 元，希望游戏时尽量跑满刷新率。",
    "我已经有 RTX 4070 显卡，剩余预算 8000 元，请配置其他配件，不要重复购买显卡。",
    "总预算 10000 元，其中需要包含显示器、键盘和鼠标，主要用于 2K 游戏。",
    "预算 6500 元，电脑需要安静、省电，机箱不能太大，不追求 RGB 灯效。",
    "公司要采购一台 3 万元以内的工作站，用于 Blender 渲染、虚幻引擎和本地 AI 推理，稳定性优先。",
    "我想要一台能玩游戏的电脑，价格合适就行。",
    "预算 3000 元，要求 4K 最高画质畅玩所有 3A 游戏，还要包含显示器。",
    "预算 20000 到 25000 元，偏好华硕和海盗船，但品牌溢价不能影响主要性能。",
    "预算四万到五万之间，但不必强行花满；要求 4K 游戏、直播和视频剪辑，至少 64GB 内存和 4TB 固态硬盘。",
]


class TwentyRequirementParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = RequirementParser()

    def test_all_twenty_prompts_parse(self) -> None:
        profiles = [self.parser.parse(prompt) for prompt in PROMPTS]
        self.assertEqual(len(profiles), 20)
        self.assertTrue(all(profile.budget_min > 0 for profile in profiles))

    def test_budget_variants(self) -> None:
        expected = {
            0: (5000, 5000, 5000),
            1: (6000, 8000, 7000),
            3: (10000, 12000, 11000),
            5: (20000, 30000, 25000),
            7: (40000, 50000, 45000),
            8: (7000, 7000, 7000),
            9: (9000, 11000, 10000),
            15: (30000, 30000, 30000),
            19: (40000, 50000, 45000),
        }
        for index, budget in expected.items():
            profile = self.parser.parse(PROMPTS[index])
            self.assertEqual((profile.budget_min, profile.budget_max, profile.budget), budget, PROMPTS[index])

    def test_parser_leaves_open_ended_semantics_to_ai(self) -> None:
        for index in [0, 6, 8, 12, 13, 19]:
            profile = self.parser.parse(PROMPTS[index])
            self.assertFalse(profile.usage_explicit)
            self.assertEqual(profile.owned_parts, {})
            self.assertFalse(profile.peripherals_explicit)

    def test_parser_only_marks_missing_budget(self) -> None:
        ambiguous = self.parser.parse(PROMPTS[16])
        self.assertFalse(ambiguous.budget_explicit)
        impossible = self.parser.parse(PROMPTS[17])
        self.assertIsNone(impossible.impossible_reason)


if __name__ == "__main__":
    unittest.main()
