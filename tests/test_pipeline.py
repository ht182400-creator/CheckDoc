# encoding: utf-8
"""MemoAlign 专项测试——并发/线程/时序敏感场景（无法 JSON 数据化）。

常态用例通过 tests/test_runner.py + tests/test_data.json 驱动。
运行：python -m unittest tests.test_pipeline
"""
import json
import os
import tempfile
import threading
import unittest


def _write(root, rel, text):
    full = os.path.join(root, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(text)
    return full


class TestConcurrencyExtract(unittest.TestCase):
    """TC01-TC03：多线程并发提取。"""

    def test_TC01_concurrent_extract_12files_3threads(self):
        """输入：12 个 md 文件 / 操作：3 线程并发 extract / 期望：无异常。"""
        with tempfile.TemporaryDirectory() as d:
            for i in range(12):
                _write(d, f"A/memory/f{i}.md", f"# File {i}\npython async content.\n## 规避\nuse pool.")
            from src.scanner import scan_memory_md
            from src.extractor import extract
            metas = scan_memory_md(d)
            errors = []

            def worker(mlist):
                for m in mlist:
                    try:
                        extract(m)
                    except Exception as exc:
                        errors.append(str(exc))

            threads = [threading.Thread(target=worker, args=(metas[i::3],)) for i in range(3)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(errors, [], f"并发提取异常: {errors}")

    def test_TC02_concurrent_keyword_reload_4readers_1writer(self):
        """输入：关键词模块 / 操作：4 线程读 + 1 线程 reload / 期望：无竞态。"""
        from src.keywords import reload, get_all_known_keywords
        errors = []

        def reader():
            for _ in range(30):
                try:
                    _ = len(get_all_known_keywords())
                except Exception as exc:
                    errors.append(str(exc))

        def re_loader():
            for _ in range(10):
                try:
                    reload()
                except Exception as exc:
                    errors.append(str(exc))

        threads = [threading.Thread(target=reader) for _ in range(4)]
        threads.append(threading.Thread(target=re_loader))
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [], f"关键词并发异常: {errors}")

    def test_TC03_concurrent_discovery_10threads(self):
        """输入：候选发现模块 / 操作：10 线程并发写 / 期望：不崩溃且产出候选。"""
        from src.keywords_discovery import reset_candidates, discover_from_text, get_candidates
        errors = []

        def worker(text):
            try:
                discover_from_text(text)
            except Exception as exc:
                errors.append(str(exc))

        reset_candidates()
        threads = [threading.Thread(target=worker, args=(f"# Test {i}\nuse `tool{i}`",))
                   for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [], f"候选发现并发异常: {errors}")
        self.assertGreaterEqual(len(get_candidates()), 1)


class TestException(unittest.TestCase):
    """TC04-TC08：异常/时序敏感场景。"""

    def test_TC04_file_deleted_between_scan_extract(self):
        """输入：存在后删除的 md / 操作：scan → delete → extract / 期望：不崩溃。"""
        with tempfile.TemporaryDirectory() as d:
            p = _write(d, "A/memory/gone.md", "# Gone\ncontent")
            from src.scanner import scan_memory_md
            metas = scan_memory_md(d)
            os.remove(p)
            from src.extractor import extract
            recs = extract(metas[0])
            self.assertIsInstance(recs, list)
            rec = recs[0]
            self.assertIsInstance(rec, dict)

    def test_TC05_binary_md_encoding_fallback(self):
        """输入：随机字节 .md / 操作：extract / 期望：不崩溃，产出 dict。"""
        with tempfile.TemporaryDirectory() as d:
            import struct
            bad = struct.pack("B" * 100, *range(256)[:100])
            f = os.path.join(d, "A/memory/bin.md")
            os.makedirs(os.path.dirname(f), exist_ok=True)
            with open(f, "wb") as fh:
                fh.write(bad)
            from src.scanner import scan_memory_md
            from src.extractor import extract
            metas = scan_memory_md(d)
            recs = extract(metas[0])
            self.assertIsInstance(recs, list)
            rec = recs[0]
            self.assertIsInstance(rec, dict)

    def test_TC06_force_llm_raises_without_key(self):
        """输入：普通 md / 操作：extract(force_llm=True) / 期望：RuntimeError。"""
        with tempfile.TemporaryDirectory() as d:
            _write(d, "A/memory/llm.md", "# LLM\ncontent")
            from src.scanner import scan_memory_md
            from src.extractor import extract
            with self.assertRaises(RuntimeError):
                extract(scan_memory_md(d)[0], force_llm=True)

    def test_TC07_normal_extract_with_llm_disabled(self):
        """输入：普通 md / 操作：extract()（LLM 关闭） / 期望：正常走规则抽取。"""
        with tempfile.TemporaryDirectory() as d:
            _write(d, "A/memory/normal.md", "# Normal\ncontent")
            from src.scanner import scan_memory_md
            from src.extractor import extract
            recs = extract(scan_memory_md(d)[0])
            rec = recs[0]
            self.assertIn("content", rec)
            self.assertIn("_raw", rec)

    def test_TC08_corrupted_cache_json_rebuild(self):
        """输入：损坏 JSON 缓存 / 操作：load_cache / 期望：返回 {}。"""
        from src import config as cfg
        from src import store as st
        old = cfg.CACHE_DIR
        try:
            cfg.CACHE_DIR = tempfile.mkdtemp()
            p = os.path.join(cfg.CACHE_DIR, cfg.CACHE_FILE)
            with open(p, "w") as f:
                f.write("{ not json !!!")
            self.assertEqual(st.load_cache(), {})
        finally:
            cfg.CACHE_DIR = old


if __name__ == "__main__":
    unittest.main()
