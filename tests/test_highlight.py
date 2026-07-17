# encoding: utf-8
"""代码高亮（P2-4）资源与开关校验：确保详情页高亮能正确注入。

运行：python -m unittest tests.test_highlight -v
"""
import unittest

from src import config, ui_app


class TestCodeHighlight(unittest.TestCase):
    """校验高亮开关与注入的 head HTML 资源。"""

    def test_enabled_flag_is_bool(self):
        self.assertIsInstance(config.CODE_HIGHLIGHT_ENABLED, bool)

    def test_head_html_loads_highlightjs(self):
        html = ui_app.HIGHLIGHT_HEAD_HTML
        self.assertIn("highlight.js", html)
        self.assertIn("cdn.jsdelivr.net", html)

    def test_head_html_uses_configured_theme(self):
        html = ui_app.HIGHLIGHT_HEAD_HTML
        self.assertIn(config.CODE_HIGHLIGHT_THEME, html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
