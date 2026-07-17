# encoding: utf-8
"""定时增量同步（P2-3）单元测试：差异计算与汇总。

运行：python -m unittest tests.test_sync -v
"""
import unittest

from src import sync


def _rec(path, mtime=1.0, content="x"):
    return {"_path": path, "_mtime": mtime, "content": content}


class TestComputeDiff(unittest.TestCase):
    """compute_diff：新增/变更/移除三类差异。"""

    def test_no_change(self):
        recs = [_rec("a.md", 1.0), _rec("b.md", 2.0)]
        diff = sync.compute_diff(recs, list(recs))
        self.assertEqual(diff["added"], [])
        self.assertEqual(diff["changed"], [])
        self.assertEqual(diff["removed"], [])

    def test_added(self):
        old = [_rec("a.md", 1.0)]
        new = [_rec("a.md", 1.0), _rec("b.md", 2.0)]
        diff = sync.compute_diff(old, new)
        self.assertEqual(len(diff["added"]), 1)
        self.assertEqual(diff["added"][0]["_path"], "b.md")
        self.assertEqual(diff["removed"], [])
        self.assertEqual(diff["changed"], [])

    def test_removed(self):
        old = [_rec("a.md", 1.0), _rec("b.md", 2.0)]
        new = [_rec("a.md", 1.0)]
        diff = sync.compute_diff(old, new)
        self.assertEqual(len(diff["removed"]), 1)
        self.assertEqual(diff["removed"][0]["_path"], "b.md")
        self.assertEqual(diff["added"], [])

    def test_changed_by_mtime(self):
        old = [_rec("a.md", 1.0)]
        new = [_rec("a.md", 5.0)]  # mtime 变化 → 变更
        diff = sync.compute_diff(old, new)
        self.assertEqual(len(diff["changed"]), 1)
        self.assertEqual(diff["changed"][0]["_mtime"], 5.0)
        self.assertEqual(diff["added"], [])
        self.assertEqual(diff["removed"], [])

    def test_changed_content_same_mtime_not_flagged(self):
        # 仅内容变化但 mtime 相同：按设计不判为变更（依赖 mtime 驱动增量）
        old = [_rec("a.md", 1.0, content="old")]
        new = [_rec("a.md", 1.0, content="new")]
        diff = sync.compute_diff(old, new)
        self.assertEqual(diff["changed"], [])

    def test_ignores_records_without_path(self):
        old = [_rec("a.md", 1.0), {"content": "no-path"}]
        new = [_rec("a.md", 1.0), {"content": "no-path"}]
        diff = sync.compute_diff(old, new)
        self.assertEqual(diff["added"], [])
        self.assertEqual(diff["removed"], [])
        self.assertEqual(diff["changed"], [])


class TestSummarize(unittest.TestCase):
    """summarize：人类可读摘要。"""

    def test_format(self):
        diff = {"added": [1], "changed": [1, 2], "removed": []}
        self.assertEqual(sync.summarize(diff), "新增 1 · 变更 2 · 移除 0")


if __name__ == "__main__":
    unittest.main(verbosity=2)
