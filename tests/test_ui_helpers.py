# encoding: utf-8
"""UI 纯函数辅助层（_ui_helpers）单元校验（W8）。

覆盖从 ui_app 拆分出的可单测纯逻辑：时间范围判定、记录查找、记录扁平化、
表格列生成。不涉及 NiceGUI 控件（_render_chips 依赖 UI，单独冒烟由 verify 导入覆盖）。

运行：python -m unittest tests.test_ui_helpers -v
"""
import time
import unittest

from src import _ui_helpers as H
from src import _ui_state as S
from src import config


class TestRecordWithinTimeRange(unittest.TestCase):
    """record_within_time_range 时间范围判定（W8，原分散在 _apply_filters）。"""

    def test_days_zero_means_unlimited(self):
        # days<=0 表示不限，任何记录都通过
        self.assertTrue(H.record_within_time_range({"_mtime": 0}, 0))
        self.assertTrue(H.record_within_time_range({}, -1))

    def test_missing_mtime_passes(self):
        # 无 _mtime 视为通过，避免误过滤历史数据
        self.assertTrue(H.record_within_time_range({}, 7))

    def test_recent_record_passes(self):
        now = time.time()
        self.assertTrue(H.record_within_time_range({"_mtime": now}, 7))

    def test_old_record_filtered(self):
        old = time.time() - 365 * config.SECONDS_PER_DAY
        self.assertFalse(H.record_within_time_range({"_mtime": old}, 7))

    def test_boundary_within_range(self):
        # 刚好 6 天前，7 天窗口内应通过
        six_days_ago = time.time() - 6 * config.SECONDS_PER_DAY
        self.assertTrue(H.record_within_time_range({"_mtime": six_days_ago}, 7))

    def test_boundary_out_of_range(self):
        # 刚好 8 天前，7 天窗口外应过滤
        eight_days_ago = time.time() - 8 * config.SECONDS_PER_DAY
        self.assertFalse(H.record_within_time_range({"_mtime": eight_days_ago}, 7))


class TestFindRecordById(unittest.TestCase):
    """_find_record_by_id 按 id 查找原记录（就地修改用）。"""

    def setUp(self):
        S.records = [
            {"id": 1, "content": "a"},
            {"id": 2, "content": "b"},
        ]

    def tearDown(self):
        S.records = []

    def test_find_existing(self):
        self.assertEqual(H._find_record_by_id(2)["content"], "b")

    def test_find_missing_returns_none(self):
        self.assertIsNone(H._find_record_by_id(999))


class TestFlattenRecords(unittest.TestCase):
    """_flatten_records 将 MULTI 列表字段转为逗号字符串（不改原数据）。"""

    def test_multi_field_joined(self):
        rows = [{"language": ["Python", "Go"], "content": "x"}]
        out = H._flatten_records(rows)
        self.assertEqual(out[0]["language"], "Python, Go")
        # 原数据不被修改
        self.assertEqual(rows[0]["language"], ["Python", "Go"])

    def test_scalar_field_untouched(self):
        rows = [{"language": ["Python"], "content": "hello"}]
        out = H._flatten_records(rows)
        self.assertEqual(out[0]["content"], "hello")


class TestBuildColumns(unittest.TestCase):
    """_build_columns 由 SCHEMA 生成列，并追加质量分列。"""

    def test_includes_all_schema_fields(self):
        cols = H._build_columns()
        names = [c["name"] for c in cols]
        for f in config.SCHEMA:
            self.assertIn(f.key, names)

    def test_appends_quality_score_column(self):
        cols = H._build_columns()
        names = [c["name"] for c in cols]
        self.assertIn(config.QUALITY_SCORE_KEY, names)

    def test_text_column_wraps(self):
        cols = H._build_columns()
        content_col = next(c for c in cols if c["name"] == "content")
        self.assertIn("white-space:normal", content_col.get("style", ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
