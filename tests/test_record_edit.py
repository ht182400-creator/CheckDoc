# encoding: utf-8
"""记录编辑（P3）单元测试：merge_edit / 低分判定 / 低分定位。

运行：python -m unittest tests.test_record_edit -v
"""
import unittest

from src import config, record_edit


def _rec(score=None, content="c", typ="陷阱") -> dict:
    """构造一条记录，score=None 表示未评分。"""
    r = {"content": content, "type": typ, "_path": "/a/b.md", "id": 1}
    if score is not None:
        r[config.QUALITY_SCORE_KEY] = score
    return r


class TestMergeEdit(unittest.TestCase):
    """merge_edit：仅覆盖 Schema 字段，保留内部字段。"""

    def test_updates_schema_fields(self):
        rec = _rec(score=80)
        record_edit.merge_edit(rec, {"content": "新内容", "type": "最佳实践"}, config.SCHEMA)
        self.assertEqual(rec["content"], "新内容")
        self.assertEqual(rec["type"], "最佳实践")

    def test_keeps_internal_fields(self):
        rec = _rec(score=80)
        record_edit.merge_edit(rec, {"content": "x"}, config.SCHEMA)
        self.assertEqual(rec["_path"], "/a/b.md")   # 内部字段不丢
        self.assertEqual(rec["id"], 1)

    def test_ignores_non_schema_keys(self):
        rec = _rec(score=80)
        record_edit.merge_edit(rec, {"_path": "/evil", "content": "x"}, config.SCHEMA)
        self.assertEqual(rec["_path"], "/a/b.md")   # 不被外部注入覆盖


class TestIsLowScore(unittest.TestCase):
    """is_low_score：低分或"未评分"为真，达中/高分为假。"""

    def test_unscored_is_low(self):
        self.assertTrue(record_edit.is_low_score(_rec(score=None)))

    def test_low_is_low(self):
        self.assertTrue(record_edit.is_low_score(_rec(score=50)))

    def test_mid_is_not_low(self):
        self.assertFalse(record_edit.is_low_score(_rec(score=config.QUALITY_MID_THRESHOLD)))

    def test_high_is_not_low(self):
        self.assertFalse(record_edit.is_low_score(_rec(score=95)))


class TestNextLowScore(unittest.TestCase):
    """next_low_score：返回首个低分/未评分记录。"""

    def test_returns_first_low(self):
        recs = [_rec(score=90), _rec(score=40), _rec(score=None)]
        self.assertIs(record_edit.next_low_score(recs), recs[1])

    def test_returns_unscored(self):
        recs = [_rec(score=90), _rec(score=None)]
        self.assertIs(record_edit.next_low_score(recs), recs[1])

    def test_none_when_all_high(self):
        recs = [_rec(score=90), _rec(score=85)]
        self.assertIsNone(record_edit.next_low_score(recs))


if __name__ == "__main__":
    unittest.main(verbosity=2)
