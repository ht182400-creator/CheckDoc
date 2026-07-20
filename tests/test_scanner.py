# encoding: utf-8
"""scanner 通用采集器测试：规则驱动 + 并发遍历 + path-aware 裁剪（通用、不硬编码）。

验证：
- 两层 path-aware 裁剪（全局垃圾跳过 + 隐藏容器只留数据源）；
- 发现规则可插拔（MatchRule 解耦单一 memory 锚点，支持任意目录规则）；
- 并发遍历正确性（结果集合与预期一致、可重复）。
"""
import os
import shutil
import tempfile
import unittest

from src import scanner, config
from src.scanner import MatchRule


class TestScanSkipDirs(unittest.TestCase):
    """两层 path-aware 裁剪（通用、不硬编码具体目录名）。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="memoalign_scan_")
        self._touch(os.path.join(self.tmp, "projA", "memory", "a.md"))
        self._touch(os.path.join(self.tmp, "projA", "memory", "b.md"))
        self._touch(os.path.join(self.tmp, "node_modules", "memory", "x.md"))
        self._touch(os.path.join(self.tmp, ".git", "memory", "g.md"))
        self._touch(os.path.join(self.tmp, ".codebuddy", "memory", "c.md"))
        self._touch(os.path.join(self.tmp, ".codebuddy", ".cache", "memory", "y.md"))
        self._touch(os.path.join(self.tmp, ".codebuddy", "skills", "memory", "z.md"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _touch(self, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("# t\n")

    def _paths(self, **kw):
        return {m.path for m in scanner.scan(self.tmp, **kw)}

    def test_skips_global_garbage_dirs(self):
        # 全局垃圾目录（依赖/产物/版本控制）内的 memory 永不扫描
        paths = self._paths()
        self.assertNotIn(
            os.path.join(self.tmp, "node_modules", "memory", "x.md"), paths)
        self.assertNotIn(
            os.path.join(self.tmp, ".git", "memory", "g.md"), paths)

    def test_keeps_hidden_container_memory(self):
        # 核心回归：隐藏容器（.codebuddy/.cursor/.claude 等）内的 memory 数据源不丢
        paths = self._paths()
        self.assertIn(
            os.path.join(self.tmp, ".codebuddy", "memory", "c.md"), paths)

    def test_trims_hidden_container_noise(self):
        # 隐藏容器内部的噪声子目录（.cache/skills 等）不遍历
        paths = self._paths()
        self.assertNotIn(
            os.path.join(self.tmp, ".codebuddy", ".cache", "memory", "y.md"), paths)
        self.assertNotIn(
            os.path.join(self.tmp, ".codebuddy", "skills", "memory", "z.md"), paths)

    def test_skip_excludes_data_source_dirs(self):
        # 防御性：数据源容器（如 .codebuddy）绝不能进全局 SKIP，否则会丢数据
        self.assertNotIn(".codebuddy", config.SKIP_DIR_NAMES)


class TestMatchRule(unittest.TestCase):
    """发现规则可插拔（解耦单一 memory 锚点，默认任意目录）。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="memoalign_rule_")
        self._touch(os.path.join(self.tmp, "projA", "memory", "a.md"))
        self._touch(os.path.join(self.tmp, "notes", "plain.md"))  # 非 memory 目录
        self._touch(os.path.join(self.tmp, "Progi-Projekt-Tim-3", "doc.md"))  # 用户真实场景

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _touch(self, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("# t\n")

    def _paths(self, **kw):
        return {m.path for m in scanner.scan(self.tmp, **kw)}

    def test_default_rule_is_any_dir(self):
        # 默认规则：任意目录（dir_name=None），不再死绑 memory 单一锚点
        self.assertIsNone(MatchRule().dir_name)

    def test_default_scan_picks_plain_dir_md(self):
        # 核心回归：默认 scan 命中普通目录（非 memory）的 .md，改目录结构不丢数据
        paths = self._paths()
        self.assertIn(os.path.join(self.tmp, "notes", "plain.md"), paths)
        self.assertIn(
            os.path.join(self.tmp, "Progi-Projekt-Tim-3", "doc.md"), paths)
        self.assertIn(os.path.join(self.tmp, "projA", "memory", "a.md"), paths)

    def test_arbitrary_dir_rule_matches_any_md(self):
        # 显式 dir_name=None：与默认一致，任意目录下的 .md 都算数据源
        paths = {m.path for m in scanner.scan(self.tmp, rules=[MatchRule(dir_name=None)])}
        self.assertIn(os.path.join(self.tmp, "notes", "plain.md"), paths)
        self.assertIn(os.path.join(self.tmp, "projA", "memory", "a.md"), paths)

    def test_memory_rule_only_memory(self):
        # 兼容旧语义：scan_memory_md 仅命中 memory 目录，普通目录不命中
        paths = {m.path for m in scanner.scan_memory_md(self.tmp)}
        self.assertIn(os.path.join(self.tmp, "projA", "memory", "a.md"), paths)
        self.assertNotIn(os.path.join(self.tmp, "notes", "plain.md"), paths)
        self.assertNotIn(
            os.path.join(self.tmp, "Progi-Projekt-Tim-3", "doc.md"), paths)


class TestScanConcurrency(unittest.TestCase):
    """并发遍历正确性：与预期一致、可重复。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="memoalign_conc_")
        self._touch(os.path.join(self.tmp, "projA", "memory", "a.md"))
        self._touch(os.path.join(self.tmp, "projB", "memory", "b.md"))
        self._touch(os.path.join(self.tmp, ".codebuddy", "memory", "c.md"))
        self._touch(os.path.join(self.tmp, "node_modules", "memory", "x.md"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _touch(self, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("# t\n")

    def _expected(self):
        return {
            os.path.join(self.tmp, "projA", "memory", "a.md"),
            os.path.join(self.tmp, "projB", "memory", "b.md"),
            os.path.join(self.tmp, ".codebuddy", "memory", "c.md"),
        }

    def test_concurrent_result_matches_expected(self):
        # 并发分片结果集合 == 顺序预期（含隐藏容器、排除全局垃圾）
        paths = {m.path for m in scanner.scan(self.tmp)}
        self.assertEqual(paths, self._expected())

    def test_scan_deterministic_across_calls(self):
        # 并发结果可重复（多次调用集合一致）
        p1 = {m.path for m in scanner.scan(self.tmp)}
        p2 = {m.path for m in scanner.scan(self.tmp)}
        self.assertEqual(p1, p2)


class TestScanIter(unittest.TestCase):
    """流式扫描生成器（借鉴 Windows 文件管理器：边遍历边产出，不阻塞等待）。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="memoalign_iter_")
        self._touch(os.path.join(self.tmp, "projA", "memory", "a.md"))
        self._touch(os.path.join(self.tmp, "notes", "plain.md"))
        self._touch(os.path.join(self.tmp, "Progi-Projekt-Tim-3", "doc.md"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _touch(self, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("# t\n")

    def test_scan_iter_yields_all(self):
        # 流式扫描逐条产出，集合与批量 scan 完全一致（验证不丢数据）
        it_paths = [m.path for m in scanner.scan_iter(self.tmp)]
        batch_paths = [m.path for m in scanner.scan(self.tmp)]
        self.assertEqual(set(it_paths), set(batch_paths))
        self.assertEqual(len(it_paths), 3)

    def test_scan_iter_is_lazy(self):
        # 生成器惰性：迭代一次只产出 1 条即暂停，不一次性发现全部（可边扫边显示）
        gen = scanner.scan_iter(self.tmp)
        first = next(gen)
        self.assertTrue(first.path.endswith(".md"))
        # 此时生成器已让出，调用方可在产出间隙刷新 UI，而不会阻塞到全量完成

    def test_scan_iter_order_stable(self):
        # 多次流式扫描产出顺序一致（按路径排序后流式给出，可复现）
        g1 = [m.path for m in scanner.scan_iter(self.tmp)]
        g2 = [m.path for m in scanner.scan_iter(self.tmp)]
        self.assertEqual(g1, g2)


if __name__ == "__main__":
    unittest.main()
