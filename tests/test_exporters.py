# encoding: utf-8
"""导出器（P3）单元测试：CSV/MD/PDF/XLSX 生成与中文支持。

运行：python -m unittest tests.test_exporters -v
"""
import unittest

from src import config, exporters


def _row(content="内容示例", avoidance="规避示例", language=None, typ="陷阱",
         severity="高", tags=None, path="/a/b.md", score=100) -> dict:
    """构造一条最小表格行，供导出断言。"""
    return {
        "content": content,
        "avoidance": avoidance,
        "language": language if language is not None else ["Python"],
        "type": typ,
        "severity": severity,
        "tags": tags if tags is not None else ["t"],
        "_path": path,
        config.QUALITY_SCORE_KEY: score,
    }


class TestFlatten(unittest.TestCase):
    """flatten：列表与标量统一为字符串。"""

    def test_list_joined(self):
        self.assertEqual(exporters.flatten(["a", "b", "c"]), "a; b; c")

    def test_none_to_empty(self):
        self.assertEqual(exporters.flatten(None), "")

    def test_scalar_kept(self):
        self.assertEqual(exporters.flatten("x"), "x")


class TestBuildCsv(unittest.TestCase):
    """build_csv：UTF-8 BOM + 表头 + 数据行。"""

    def test_contains_bom_and_header(self):
        data = exporters.build_csv([_row()])
        self.assertTrue(data.startswith(b"\xef\xbb\xbf"))
        text = data.decode("utf-8")
        self.assertIn("content", text)           # 表头含 schema 字段
        self.assertIn("quality_score", text)     # 附加字段
        self.assertIn("/a/b.md", text)           # _path 写出

    def test_multivalue_flattened(self):
        data = exporters.build_csv([_row(language=["Python", "Go"], tags=["x", "y"])])
        text = data.decode("utf-8")
        self.assertIn("Python; Go", text)
        self.assertIn("x; y", text)


class TestBuildMd(unittest.TestCase):
    """build_md：按类型分组，含内容与质量分。"""

    def test_grouped_with_content(self):
        data = exporters.build_md([_row(content="坑点A", typ="陷阱")])
        text = data.decode("utf-8")
        self.assertIn("# MemoAlign 导出摘要", text)
        self.assertIn("坑点A", text)
        self.assertIn("陷阱", text)


class TestBuildPdf(unittest.TestCase):
    """build_pdf：含中文的 PDF 字节流（%PDF 头）。无 reportlab 时跳过。"""

    def test_pdf_bytes_start_with_magic(self):
        try:
            data = exporters.build_pdf([_row(content="中文内容测试", avoidance="规避方法")])
        except RuntimeError as exc:
            if "no_reportlab" in str(exc):
                self.skipTest("reportlab 未安装，跳过 PDF 断言")
            raise
        # 合法 PDF：以 %PDF 头、%%EOF 尾、且含中文 CID 字体引用
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertTrue(data.rstrip().endswith(b"%%EOF"))
        self.assertIn(b"STSong", data)        # 内置中文 CID 字体已嵌入
        self.assertGreater(len(data), 500)     # 非空的真实文档

    def test_pdf_special_chars_not_crash(self):
        """B2 回归：记录含 XML 特殊字符（& < >）不得导致 reportlab 抛 SAXParseException。"""
        try:
            data = exporters.build_pdf([
                _row(content="a & b < c > d", avoidance="if x < 5 then y & z"),
                _row(content="拼写：Tom & Jerry", typ="陷阱"),
            ])
        except RuntimeError as exc:
            if "no_reportlab" in str(exc):
                self.skipTest("reportlab 未安装，跳过 PDF 断言")
            raise
        # 能正常生成 PDF（未崩溃即代表 XML 转义生效）
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertTrue(data.rstrip().endswith(b"%%EOF"))


class TestBuildXlsx(unittest.TestCase):
    """build_xlsx：Excel 字节流；无 openpyxl 时跳过。"""

    def test_xlsx_or_skip(self):
        try:
            data = exporters.build_xlsx([_row()])
        except RuntimeError as exc:
            if "no_openpyxl" in str(exc):
                self.skipTest("openpyxl 未安装，跳过 XLSX 断言")
            raise
        # openpyxl 生成的 xlsx 以 PK(zip) 头开头
        self.assertTrue(data[:2] == b"PK")


if __name__ == "__main__":
    unittest.main(verbosity=2)
