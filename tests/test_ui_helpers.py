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


class TestParseRowClickId(unittest.TestCase):
    """_parse_row_click_id：行点击参数→id 解析（回归 rowClick args 为列表崩溃）。

    ui_app._on_row_click 在注册时显式 args=["row"]，使 e.args 即 row dict；
    该纯函数统一处理 dict / 缺失 id / 误传列表三种情况。
    """

    def test_row_dict_with_id(self):
        # 正常：args 即 row dict，含 id
        self.assertEqual(H._parse_row_click_id({"id": 7, "content": "x"}), 7)

    def test_row_dict_without_id_returns_none(self):
        # 无 id：安全跳过（不打开详情）
        self.assertIsNone(H._parse_row_click_id({"content": "x"}))

    def test_args_is_list_returns_none(self):
        # 回归：早期对 list 调 .get 崩溃；新逻辑遇非 dict 直接返回 None
        self.assertIsNone(H._parse_row_click_id(["evt", {"id": 7}, 0]))

    def test_args_none_returns_none(self):
        self.assertIsNone(H._parse_row_click_id(None))


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

    def test_raw_excluded_from_display(self):
        # 治本：整篇原文 _raw 不进前端表格（详情按 id 从服务端取）
        rows = [{"content": "x", "_raw": "非常长的整篇原文" * 50, "_path": "p"}]
        out = H._flatten_records(rows)
        self.assertNotIn("_raw", out[0])

    def test_raw_preview_excluded_from_display(self):
        # _raw_preview 同为内部大字段，瘦身后也不推前端
        rows = [{"content": "x", "_raw_preview": "预览" * 500, "id": 1}]
        out = H._flatten_records(rows)
        self.assertNotIn("_raw_preview", out[0])

    def test_text_field_truncated(self):
        # TEXT 字段超长截断为预览（完整内容由详情/导出取），避免大表推送
        long_text = "A" * (config.CONTENT_PREVIEW_MAX + 100)
        rows = [{"content": long_text, "id": 1}]
        out = H._flatten_records(rows)
        self.assertEqual(len(out[0]["content"]), config.CONTENT_PREVIEW_MAX + 1)
        self.assertTrue(out[0]["content"].endswith("…"))

    def test_short_text_not_truncated(self):
        rows = [{"content": "短内容", "id": 1}]
        out = H._flatten_records(rows)
        self.assertEqual(out[0]["content"], "短内容")

    def test_id_and_path_preserved(self):
        # 详情/定位所需轻量字段必须保留在显示行
        rows = [{"content": "x", "id": 7, "_path": "a/b.md", "_raw": "raw"}]
        out = H._flatten_records(rows)
        self.assertEqual(out[0]["id"], 7)
        self.assertEqual(out[0]["_path"], "a/b.md")

    def test_flatten_one_consistent_with_records(self):
        # 单条版与列表版结果一致（run_scan 增量 append 用 _flatten_one）
        r = {"content": "A" * 300, "language": ["Go"], "_raw": "big"}
        self.assertEqual(H._flatten_one(r), H._flatten_records([r])[0])
        self.assertNotIn("_raw", H._flatten_one(r))


class TestFlatten(unittest.TestCase):
    """_flatten 单值语义（全文检索共用，对齐 exporters.flatten）。"""

    def test_list_joined_with_semicolon(self):
        # 多值字段用 "; " 连接
        self.assertEqual(H._flatten(["Python", "Go"]), "Python; Go")

    def test_none_becomes_empty(self):
        self.assertEqual(H._flatten(None), "")

    def test_scalar_to_str(self):
        self.assertEqual(H._flatten("hello"), "hello")
        self.assertEqual(H._flatten(42), "42")


class TestNormalizeSearchText(unittest.TestCase):
    """_normalize_search_text：全文检索归一化（P1-1 修复中英文拼接漏匹配）。

    记录原文「向导 App …」与用户输入「向导app」必须匹配。
    """

    def test_whitespace_between_cjk_and_latin(self):
        # 核心回归：中英文之间的空格被归一化，使「向导 App」≈「向导app」
        self.assertIn(
            H._normalize_search_text("向导app"),
            H._normalize_search_text("向导 App 步骤5 永久卡在正在检测"),
        )

    def test_fullwidth_space_normalized(self):
        # 全角空格同样归一
        self.assertIn(
            H._normalize_search_text("python函数"),
            H._normalize_search_text("python　函数（陷阱）"),
        )

    def test_case_insensitive(self):
        self.assertIn(
            H._normalize_search_text("PYTHON"),
            H._normalize_search_text("python 陷阱"),
        )

    def test_newline_and_tab_normalized(self):
        # 换行/制表符归一，长文本跨行仍可检索
        self.assertIn(
            H._normalize_search_text("nohup重定向"),
            H._normalize_search_text("正确姿势：\nnohup 重定向到文件"),
        )

    def test_none_returns_empty(self):
        self.assertEqual(H._normalize_search_text(None), "")

    def test_normal_plain_match_still_works(self):
        # 普通无空格关键词不受影响
        self.assertIn(
            H._normalize_search_text("python"),
            H._normalize_search_text("python 训练向导"),
        )


class TestResolveExportScope(unittest.TestCase):
    """_resolve_export_scope：导出范围下拉解析（全部记录/当前可见）。

    下拉为 "all" → "all"；其余（含 None/未初始化）→ 回落 "visible"。
    """

    def tearDown(self):
        # 还原全局状态，避免影响后续用例
        S.export_scope = None

    def test_all_returns_all(self):
        S.export_scope = type("Sel", (), {"value": "all"})()
        self.assertEqual(H._resolve_export_scope(), "all")

    def test_visible_returns_visible(self):
        S.export_scope = type("Sel", (), {"value": "visible"})()
        self.assertEqual(H._resolve_export_scope(), "visible")

    def test_none_scope_falls_back_to_visible(self):
        S.export_scope = None
        self.assertEqual(H._resolve_export_scope(), "visible")

    def test_unknown_value_falls_back_to_visible(self):
        S.export_scope = type("Sel", (), {"value": "其他"})()
        self.assertEqual(H._resolve_export_scope(), "visible")


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
