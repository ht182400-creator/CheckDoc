# encoding: utf-8
"""质量评分（P2-2）单元测试：启发式评分、等级映射、LLM 回落与批量打分。

运行：python -m unittest tests.test_quality -v
"""
import os
import unittest
from typing import Dict

from src import config, quality_scorer


def _rec(content="", avoidance="", language=None, platform=None,
         typ="", severity="", tags=None) -> Dict:
    """构造一条最小记录，便于评分断言。"""
    return {
        "content": content,
        "avoidance": avoidance,
        "language": language if language is not None else ["通用"],
        "platform": platform if platform is not None else ["跨平台"],
        "type": typ,
        "severity": severity,
        "tags": tags if tags is not None else [],
    }


class TestHeuristicScore(unittest.TestCase):
    """启发式评分：字段完整度累加（满分 100）。"""

    def test_full_record_scores_100(self):
        rec = _rec(content="x", avoidance="y", language=["Python"],
                   typ="陷阱", severity="高", tags=["a", "b"])
        self.assertEqual(quality_scorer.heuristic_score(rec), 100)

    def test_empty_record_scores_0(self):
        rec = _rec(content="", avoidance="", language=["通用"],
                   typ="其他", severity="", tags=[])
        self.assertEqual(quality_scorer.heuristic_score(rec), 0)

    def test_partial_record_boundaries(self):
        # 仅内容 + 规避 + 严重度 = 20+20+15 = 55
        rec = _rec(content="x", avoidance="y", severity="中")
        self.assertEqual(quality_scorer.heuristic_score(rec), 55)
        # 语言命中（非通用）额外 +20；类型非其他 +15；标签 +10 → 55+45=100
        rec2 = _rec(content="x", avoidance="y", language=["Go"],
                    typ="最佳实践", severity="中", tags=["t"])
        self.assertEqual(quality_scorer.heuristic_score(rec2), 100)

    def test_severity_not_in_options_no_credit(self):
        # severity 不在 SEVERITY_OPTIONS 时不给分
        rec = _rec(content="x", avoidance="y", severity="未知")
        self.assertEqual(quality_scorer.heuristic_score(rec), 40)

    def test_language_only_generic_no_credit(self):
        # 语言仅为「通用」不给分，但命中具体语言给分
        rec_gen = _rec(content="x", language=["通用"])
        rec_py = _rec(content="x", language=["Python"])
        self.assertEqual(quality_scorer.heuristic_score(rec_gen), 20)
        self.assertEqual(quality_scorer.heuristic_score(rec_py), 40)


class TestTierOf(unittest.TestCase):
    """分数 → 等级映射。"""

    def test_none_is_unscored(self):
        self.assertEqual(quality_scorer.tier_of(None), config.QUALITY_TIER_NONE)

    def test_boundaries(self):
        self.assertEqual(quality_scorer.tier_of(100), "高")
        self.assertEqual(quality_scorer.tier_of(80), "高")
        self.assertEqual(quality_scorer.tier_of(79), "中")
        self.assertEqual(quality_scorer.tier_of(60), "中")
        self.assertEqual(quality_scorer.tier_of(59), "低")
        self.assertEqual(quality_scorer.tier_of(0), "低")


class TestScoreRecord(unittest.TestCase):
    """score_record：LLM 可用走 LLM，否则/heuristic 回落。"""

    def test_no_llm_falls_back_to_heuristic(self):
        # LLM 未启用 → 直接启发式
        saved = config.LLM_ENABLED
        config.LLM_ENABLED = False
        try:
            rec = _rec(content="x", avoidance="y", language=["Python"],
                       typ="陷阱", severity="高", tags=["t"])
            self.assertEqual(quality_scorer.score_record(rec, llm=True), 100)
        finally:
            config.LLM_ENABLED = saved

    def test_llm_path_returns_llm_score(self):
        # 启用 LLM 且配置密钥时走 _llm_score；monkeypatch 返回 90，验证被采用
        saved_en = config.LLM_ENABLED
        saved_key = config.LLM_API_KEY
        config.LLM_ENABLED = True
        config.LLM_API_KEY = "test-key"
        orig = quality_scorer._llm_score
        try:
            quality_scorer._llm_score = lambda r: 90
            rec = _rec(content="x")
            self.assertEqual(quality_scorer.score_record(rec, llm=True), 90)
        finally:
            quality_scorer._llm_score = orig
            config.LLM_ENABLED = saved_en
            config.LLM_API_KEY = saved_key

    def test_llm_failure_falls_back_to_heuristic(self):
        # _llm_score 抛异常 → 回落启发式（不向上传播）
        saved = config.LLM_ENABLED
        config.LLM_ENABLED = True
        orig = quality_scorer._llm_score
        try:
            def _boom(r):
                raise RuntimeError("network down")
            quality_scorer._llm_score = _boom
            rec = _rec(content="x", avoidance="y", severity="高")
            # 启发式 = 20+20+15 = 55
            self.assertEqual(quality_scorer.score_record(rec, llm=True), 55)
        finally:
            quality_scorer._llm_score = orig
            config.LLM_ENABLED = saved


class TestScoreRecords(unittest.TestCase):
    """score_records：就地写入 quality_score。"""

    def test_in_place_writes_score(self):
        recs = [_rec(content="a", avoidance="b", language=["Rust"],
                     typ="规范", severity="中", tags=["t"]),
                _rec(content="", language=["通用"], typ="其他")]
        quality_scorer.score_records(recs)
        self.assertEqual(recs[0][config.QUALITY_SCORE_KEY], 100)
        self.assertEqual(recs[1][config.QUALITY_SCORE_KEY], 0)

    def test_skips_non_dict(self):
        recs = [_rec(content="a"), "not-a-dict", None]
        # 不应抛异常；非 dict 项保持原样，仅 dict 项被评分
        quality_scorer.score_records(recs)
        self.assertEqual(recs[0][config.QUALITY_SCORE_KEY], 20)
        self.assertEqual(recs[1], "not-a-dict")
        self.assertIsNone(recs[2])


if __name__ == "__main__":
    unittest.main(verbosity=2)
