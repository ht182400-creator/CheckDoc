# encoding: utf-8
"""JSON 驱动全量测试运行器——详细分级日志版。

用法：python -m unittest tests.test_runner
日志：tests/test_run.log（每次运行追加，含 START/PASS/FAIL/模块汇总）
"""
import json
import logging
import os
import sys
import tempfile
import time
import traceback
import unittest
from collections import defaultdict

# ---- 测试日志（带时间戳文件名 + DEBUG/INFO/WARNING/ERROR 四级） ----
_LOG_FILE = os.path.join(
    os.path.dirname(__file__),
    f"test_run_{time.strftime('%Y%m%d_%H%M%S')}.log")
_LOG = logging.getLogger("test_runner")
_LOG.setLevel(logging.DEBUG)
_LOG.handlers.clear()
_fh = logging.FileHandler(_LOG_FILE, encoding="utf-8")
_fh.setFormatter(logging.Formatter(
    "[%(asctime)s.%(msecs)03d] %(levelname)-7s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"))
_LOG.addHandler(_fh)

_LOG.info("=" * 70)
_LOG.info("MemoAlign 测试运行开始  %s", time.strftime("%Y-%m-%d %H:%M:%S"))
_LOG.info("日志文件: %s", os.path.basename(_LOG_FILE))

_DATA = os.path.join(os.path.dirname(__file__), "test_data.json")
with open(_DATA, "r", encoding="utf-8") as _f:
    TD = json.load(_f)

# 模块级统计：{module: {"pass":0, "fail":0, "error":0, "total":0}}
_SUMMARY = defaultdict(lambda: {"pass": 0, "fail": 0, "error": 0, "total": 0})


def _w(root, rel, text):
    f = os.path.join(root, rel)
    os.makedirs(os.path.dirname(f), exist_ok=True)
    with open(f, "w", encoding="utf-8") as fh:
        fh.write(text)
    return f


def _wb(root, rel, data):
    f = os.path.join(root, rel)
    os.makedirs(os.path.dirname(f), exist_ok=True)
    with open(f, "wb") as fh:
        fh.write(data)
    return f


def _setup(d, case):
    for e in (case.get("files") or []):
        _w(d, e[0], e[1] if len(e) > 1 else "")
    for de in (case.get("dirs") or []):
        os.makedirs(os.path.join(d, de), exist_ok=True)


def _ver(exp, raw):
    """验证器：返回 (ok, detail_msg)。"""
    if not isinstance(exp, dict):
        return raw == exp, f"期望={exp!r} 实际={raw!r}" if raw != exp else ""
    for k, v in exp.items():
        if isinstance(raw, dict):
            rv = raw.get(k, raw)
        else:
            rv = raw
        if k == "language_contains":
            for x in v:
                if x not in raw.get("language", []):
                    return False, f"language 应含 {x}，实际={raw.get('language')}"
        elif k == "platform_contains":
            for x in v:
                if x not in raw.get("platform", []):
                    return False, f"platform 应含 {x}，实际={raw.get('platform')}"
        elif k == "avoidance_contains":
            if v not in raw.get("avoidance", ""):
                return False, f"avoidance 应含 '{v}'，实际='{raw.get('avoidance','')[:80]}'"
        elif k == "source_contains":
            if v not in raw.get("source", ""):
                return False, f"source 应含 '{v}'，实际='{raw.get('source')}'"
        elif k == "language_eq":
            if raw.get("language") != v:
                return False, f"language 应为 {v}，实际={raw.get('language')}"
        elif k == "platform_eq":
            if raw.get("platform") != v:
                return False, f"platform 应为 {v}，实际={raw.get('platform')}"
        elif k in ("type", "content", "severity"):
            if raw.get(k) != v:
                return False, f"{k} 应为 '{v}'，实际='{raw.get(k)}'"
        elif k == "_truncated":
            av = raw.get("_truncated")
            if av != v:
                return False, f"_truncated 应为 {v}，实际={av}"
        elif k == "has_all_schema":
            from src.config import SCHEMA
            missing = [ff.key for ff in SCHEMA if ff.key not in raw]
            if missing:
                return False, f"缺少 Schema 字段: {missing}"
        elif k == "_raw_len_gt" and isinstance(raw, dict):
            rl = len(raw.get("_raw", ""))
            if rl <= v:
                return False, f"_raw 长度应为 >{v}，实际={rl}"
        elif k == "works":
            pass
    return True, ""


# ===== 核心基类——分级日志 + 统计 =====

class _Base(unittest.TestCase):
    """带分级日志的基类：模块级汇总 + 每条用例 PASS/FAIL + 耗时。"""

    _mod_name: str = ""

    @classmethod
    def setUpClass(cls):
        cls._mod_name = getattr(cls, "_mod_name", "") or cls.__name__
        _LOG.info("")
        _LOG.info("┌" + "─" * 68)
        _LOG.info("│ [模块] %s", cls._mod_name)
        _LOG.info("└" + "─" * 68)

    @classmethod
    def tearDownClass(cls):
        stats = _SUMMARY[cls._mod_name]
        total = stats["total"]
        p = stats["pass"]
        f = stats["fail"]
        e = stats["error"]
        if f + e == 0:
            _LOG.info("│ 模块通过: %d/%d PASS", p, total)
        else:
            _LOG.error("│ >>> 模块异常 <<<  %d PASS / %d FAIL / %d ERROR, total=%d", p, f, e, total)

    def setUp(self):
        self._t0 = time.time()
        # _cid/_cname/_ccat 在 test body 中由 _attach_case 设置

    def tearDown(self):
        ms = (time.time() - self._t0) * 1000
        cid = getattr(self, "_cid", "?")
        cname = getattr(self, "_cname", "")
        ccat = getattr(self, "_ccat", "")
        failed = False
        try:
            for tc, exc in self._outcome.errors:
                if tc is self and exc is not None:
                    failed = True
                    break
        except Exception:
            pass

        if failed:
            _SUMMARY[self._mod_name]["fail"] += 1
            # ANSI 红色 + 突出标记（终端支持红色，纯文本查看也醒目）
            _LOG.error("│ >>> FAIL <<<  %-12s %-35s (%6.1fms)", cid, cname[:35], ms)
        else:
            _SUMMARY[self._mod_name]["pass"] += 1
            _LOG.info("│ PASS    %-12s %-35s [%s] (%6.1fms)", cid, cname[:35], ccat, ms)
        _SUMMARY[self._mod_name]["total"] += 1


# ========== TestCase 工厂函数 ==========

def _attach_case(test_self, case):
    """挂载 case 数据并输出 DEBUG 级输入日志。"""
    cid = case.get("id", "?")
    cname = case.get("name", "?")
    test_self._cid = cid
    test_self._cname = cname
    test_self._ccat = case.get("category", "?")
    # 构建输入摘要用于 DEBUG 日志
    parts = []
    for k in ("func", "op", "file", "files", "root", "records", "input", "args"):
        v = case.get(k)
        if v is None:
            continue
        if isinstance(v, list) and len(v) > 0:
            item = v[0]
            if isinstance(item, str):
                parts.append(f"{k}={item[:60]}") if len(v) == 2 else parts.append(f"{k}=[{len(v)} items]")
            else:
                parts.append(f"{k}=[{len(v)} items]")
        elif isinstance(v, str):
            parts.append(f"{k}={v[:60]}")
        elif isinstance(v, (int, float, bool)):
            parts.append(f"{k}={v}")
    info = "; ".join(parts[:5])
    exp_summary = _expected_str(case.get("expected", {}))
    _LOG.debug("│   %-12s %-35s  输入: %s", cid, cname[:35], info)
    if exp_summary:
        _LOG.debug("│   %-12s %-35s  期望: %s", "", "", exp_summary)


def _expected_str(exp):
    """构建期望值的可读摘要。"""
    if not exp:
        return ""
    if isinstance(exp, dict):
        items = []
        for k, v in exp.items():
            if isinstance(v, list):
                items.append(f"{k}={v}")
            elif isinstance(v, (int, float, bool)):
                items.append(f"{k}={v}")
            elif isinstance(v, str) and v:
                items.append(f"{k}={v[:40]}")
        return "; ".join(items[:5])
    if isinstance(exp, list):
        return f"list[{len(exp)}]"
    return str(exp)[:60]


# ===== Scanner =====

class TestScanner(_Base):
    _mod_name = "Scanner"


def _mk_scanner(case):
    def test(self):
        _attach_case(self, case)
        from src.scanner import scan_memory_md
        root = case.get("root")
        if root:
            result = scan_memory_md(root)
        else:
            with tempfile.TemporaryDirectory() as d:
                _setup(d, case)
                result = scan_memory_md(d)
        exp = case["expected"]
        if "count" in exp:
            self.assertEqual(len(result), exp["count"])
        if exp.get("name"):
            self.assertTrue(any(m.name == exp["name"] for m in result))
        if exp.get("sorted"):
            for i in range(len(result) - 1):
                self.assertLess(result[i].path, result[i + 1].path)
    return test

for c in TD.get("scanner", []):
    setattr(TestScanner, f"test_{c['id']}", _mk_scanner(c))


# ===== Extractor Unit =====

class TestExtractorUnit(_Base):
    _mod_name = "Extractor_Unit"


def _mk_eu(case):
    def test(self):
        _attach_case(self, case)
        from src import extractor as ex
        fn = getattr(ex, case["func"])
        args = case.get("args", [])
        if isinstance(args, str):
            result = fn(args)
        elif len(args) == 1:
            result = fn(args[0])
        else:
            result = fn(*args)
        exp = case["expected"]
        if isinstance(exp, dict):
            if "eq" in exp:
                self.assertEqual(result, exp["eq"])
            if "contains" in exp:
                for x in exp["contains"]:
                    self.assertIn(x, str(result))
        elif exp is None:
            self.assertIsNone(result)
        else:
            self.assertEqual(result, exp)
    return test

for c in TD.get("extractor_unit", []):
    setattr(TestExtractorUnit, f"test_{c['id']}", _mk_eu(c))


# ===== Extractor Pipeline =====

class TestExtractorPipeline(_Base):
    _mod_name = "Extractor_Pipeline"


def _mk_ep(case):
    def test(self):
        _attach_case(self, case)
        from src.extractor import extract
        from src.scanner import scan_memory_md
        enc = case.get("encoding", "utf-8")
        with tempfile.TemporaryDirectory() as d:
            path, content = case["file"][0], case["file"][1]
            f = os.path.join(d, path)
            os.makedirs(os.path.dirname(f), exist_ok=True)
            with open(f, "w", encoding=enc) as fh:
                fh.write(content)
            meta = scan_memory_md(d)[0]
            force = case.get("force_llm", False)
            if case["expected"].get("raises"):
                with self.assertRaises(Exception):
                    extract(meta, force_llm=force)
                return
            recs = extract(meta, force_llm=force)
            rec = recs[0] if recs else {}
            exp = case["expected"]
            ok, msg = _ver(exp, rec)
            if not ok:
                self.fail(msg)
            if "content_len_gt" in exp:
                self.assertGreater(len(rec.get("content", "")), exp["content_len_gt"])
    return test

for c in TD.get("extractor_pipeline", []):
    setattr(TestExtractorPipeline, f"test_{c['id']}", _mk_ep(c))


# ===== Store =====

class TestStore(_Base):
    _mod_name = "Store"


def _mk_st(case):
    def test(self):
        _attach_case(self, case)
        from src import store as st
        from src import config as cfg
        from src.scanner import FileMeta
        old = cfg.CACHE_DIR
        try:
            op = case["op"]
            if op == "load_cache_missing":
                cfg.CACHE_DIR = tempfile.mkdtemp()
                self.assertEqual(st.load_cache(), {})
            elif op == "load_cache_corrupted":
                cfg.CACHE_DIR = tempfile.mkdtemp()
                p = os.path.join(cfg.CACHE_DIR, cfg.CACHE_FILE)
                with open(p, "w") as f:
                    f.write(case["cache_content"])
                self.assertEqual(st.load_cache(), {})
            elif op == "load_cache_not_dict":
                cfg.CACHE_DIR = tempfile.mkdtemp()
                p = os.path.join(cfg.CACHE_DIR, cfg.CACHE_FILE)
                with open(p, "w") as f:
                    json.dump(json.loads(case["cache_content"]), f)
                self.assertEqual(st.load_cache(), {})
            elif op == "needs_update":
                mtime = case["mtime"]
                cm = case["cache_mtime"]
                meta = FileMeta(path="/x.md", name="x", project="P", mtime=mtime, size=10)
                cache = {} if cm is None else {"/x.md": {"__mtime": cm}}
                self.assertEqual(st.needs_update(meta, cache), case["expected"])
            elif op == "put_slim":
                meta = FileMeta(path="/x.md", name="x", project="P", mtime=1.0, size=10)
                rec = {"content": "test", "_raw": "a" * 3000}
                cache = {}
                st.put(cache, meta, rec)
                entry = cache["/x.md"]
                self.assertNotIn("_raw", entry["records"][0])
                self.assertIn("_raw_preview", entry["records"][0])
            elif op == "full_flow":
                with tempfile.TemporaryDirectory() as d:
                    _w(d, "M/memory/a.md", "# A\ncontent")
                    from src.scanner import scan_memory_md
                    from src.extractor import extract
                    meta = scan_memory_md(d)[0]
                    cache = st.load_cache()
                    self.assertTrue(st.needs_update(meta, cache))
                    st.put_all(cache, meta, extract(meta))
                    self.assertFalse(st.needs_update(meta, cache))
                    os.utime(meta.path, (meta.mtime + 10, meta.mtime + 10))
                    m2 = scan_memory_md(d)[0]
                    self.assertTrue(st.needs_update(m2, cache))
            elif op == "reset_remove":
                cfg.CACHE_DIR = tempfile.mkdtemp()
                p = os.path.join(cfg.CACHE_DIR, cfg.CACHE_FILE)
                cache = {}
                st.put(cache, FileMeta(path="/x.md", name="x", project="P", mtime=1.0, size=10),
                       {"content": "x", "_raw": "raw"})
                st.save_cache(cache)
                self.assertTrue(os.path.exists(p))
                st.reset()
                self.assertFalse(os.path.exists(p))
            elif op == "reset_safe":
                cfg.CACHE_DIR = tempfile.mkdtemp()
                st.reset()
        finally:
            cfg.CACHE_DIR = old
    return test

for c in TD.get("store", []):
    setattr(TestStore, f"test_{c['id']}", _mk_st(c))


# ===== Keywords =====

class TestKeywords(_Base):
    _mod_name = "Keywords"


def _mk_kw(case):
    def test(self):
        _attach_case(self, case)
        f = case["func"]
        exp = case["expected"]
        if f == "load_language_keywords":
            from src.keywords import load_language_keywords
            d = load_language_keywords()
            self.assertIn(exp["contains_key"], d)
        elif f == "load_type_keywords":
            from src.keywords import load_type_keywords
            d = load_type_keywords()
            self.assertIsInstance(d, list)
            self.assertGreater(len(d), 0)
        elif f == "load_platform_keywords":
            from src.keywords import load_platform_keywords
            self.assertIn(exp["contains_key"], load_platform_keywords())
        elif f == "load_severity_keywords":
            from src.keywords import load_severity_keywords
            self.assertIn(exp["contains_key"], load_severity_keywords())
        elif f == "load_avoidance_headers":
            from src.keywords import load_avoidance_headers
            d = load_avoidance_headers()
            self.assertIsInstance(d, list)
            self.assertIn(exp["contains"], d)
        elif f == "reload_consistent":
            from src.keywords import reload, get_all_known_keywords
            b = len(get_all_known_keywords())
            reload()
            self.assertEqual(len(get_all_known_keywords()), b)
        elif f == "get_all_known_keywords_len":
            from src.keywords import get_all_known_keywords
            self.assertGreater(len(get_all_known_keywords()), exp)
        elif f == "add_keyword":
            from src.keywords import add_keyword
            self.assertFalse(add_keyword(case["section"], case["category"], case["keyword"]))
    return test

for c in TD.get("keywords", []):
    setattr(TestKeywords, f"test_{c['id']}", _mk_kw(c))


# ===== Discovery =====

class TestDiscovery(_Base):
    _mod_name = "Discovery"


def _mk_dc(case):
    def test(self):
        _attach_case(self, case)
        from src.keywords_discovery import (
            reset_candidates, get_candidates, discover_from_text, pending_for_language
        )
        op = case.get("op", "discover")
        if op == "pending":
            self.assertEqual(pending_for_language(case["input"]), case["expected"])
            return
        if op == "reset_then_get":
            reset_candidates()
            self.assertEqual(len(get_candidates()), case["expected"])
            return
        reset_candidates()
        discover_from_text(case["input"])
        cands = get_candidates()
        cand_set = {w for w, f in cands}
        exp = case["expected"]
        if "cand_count" in exp:
            self.assertEqual(len(cands), exp["cand_count"])
        for x in (exp.get("cand_contains") or []):
            self.assertIn(x, cand_set)
        for x in (exp.get("cand_not") or []):
            self.assertNotIn(x, cand_set)
    return test

for c in TD.get("discovery", []):
    setattr(TestDiscovery, f"test_{c['id']}", _mk_dc(c))


# ===== Graph =====

class TestGraph(_Base):
    _mod_name = "Graph"


def _mk_g(case):
    def test(self):
        _attach_case(self, case)
        from src.graph_view import build_graph_option
        records = []
        for r in (case.get("records") or []):
            records.append({
                "content": r[0], "language": r[1] if len(r) > 1 else [],
                "type": r[2] if len(r) > 2 else "", "severity": r[3] if len(r) > 3 else "中",
                "tags": r[4] if len(r) > 4 else [], "platform": r[5] if len(r) > 5 else ["跨平台"]
            })
        opt = build_graph_option(records, mode="network")
        exp = case["expected"]
        if "title_contains" in exp:
            self.assertIn(exp["title_contains"], opt.get("title", {}).get("text", ""))
        if "series" not in opt:
            return
        for k in ("nodes", "links"):
            if k in exp:
                self.assertEqual(len(opt["series"][0]["data"]) if k == "nodes" else len(opt["series"][0]["links"]), exp[k])
        if "links_ge" in exp:
            self.assertGreaterEqual(len(opt["series"][0]["links"]), exp["links_ge"])
        if exp.get("max_size_gt_min"):
            sizes = [n["symbolSize"] for n in opt["series"][0]["data"]]
            self.assertGreater(max(sizes), min(sizes))
        s = opt["series"][0]
        for k in ("graph_type", "layout"):
            if k in exp:
                self.assertEqual(s[k.replace("graph_", "")], exp[k])
        if "draggable" in exp:
            self.assertTrue(s["draggable"])
    return test

for c in TD.get("graph", []):
    setattr(TestGraph, f"test_{c['id']}", _mk_g(c))


# ===== Boundary =====

class TestBoundary(_Base):
    _mod_name = "Boundary"


def _mk_b(case):
    def test(self):
        _attach_case(self, case)
        from src import config as cfg
        from src.scanner import scan_memory_md
        from src.extractor import extract
        op = case.get("op", "")
        exp = case.get("expected", {})
        if op == "chunk_limit_exact":
            with tempfile.TemporaryDirectory() as d:
                _w(d, "A/memory/big.md", "x" * cfg.READ_CHUNK_LIMIT)
                self.assertTrue(extract(scan_memory_md(d)[0])[0].get("_truncated"))
        elif op == "chunk_limit_minus1":
            with tempfile.TemporaryDirectory() as d:
                _w(d, "A/memory/big.md", "x" * (cfg.READ_CHUNK_LIMIT - 1))
                self.assertFalse(extract(scan_memory_md(d)[0])[0].get("_truncated"))
        elif "file" in case:
            with tempfile.TemporaryDirectory() as d:
                path, content = case["file"][0], case["file"][1]
                _w(d, path, content)
                recs = extract(scan_memory_md(d)[0])
                rec = recs[0]
                if "content_len_gt" in exp:
                    self.assertGreater(len(rec.get("content", "")), exp["content_len_gt"])
        elif "files" in case:
            with tempfile.TemporaryDirectory() as d:
                _setup(d, case)
                metas = scan_memory_md(d)
                if "count" in exp:
                    self.assertEqual(len(metas), exp["count"])
    return test

for c in TD.get("boundary", []):
    setattr(TestBoundary, f"test_{c['id']}", _mk_b(c))


# ===== Exception =====

class TestException(_Base):
    _mod_name = "Exception"


def _mk_ex(case):
    def test(self):
        _attach_case(self, case)
        from src.scanner import scan_memory_md, FileMeta
        from src.extractor import extract
        op = case.get("op", "")
        if "func" in case:
            from src import extractor as ex
            fn = getattr(ex, case["func"])
            result = fn(case["args"][0]) if len(case.get("args", [])) == 1 else fn(*case.get("args", []))
            self.assertEqual(result, case["expected"])
            return
        if "files" in case:
            with tempfile.TemporaryDirectory() as d:
                _setup(d, case)
                self.assertEqual(len(scan_memory_md(d)), case["expected"]["count"])
            return
        if op == "file_deleted":
            with tempfile.TemporaryDirectory() as d:
                p = _w(d, "A/memory/gone.md", "# Gone\nc")
                metas = scan_memory_md(d)
                os.remove(p)
                recs = extract(metas[0])
                rec = recs[0]
                self.assertIsInstance(rec, dict)
        elif op == "binary_md":
            with tempfile.TemporaryDirectory() as d:
                _wb(d, "A/memory/bin.md", bytes(range(128, 256)))
                metas = scan_memory_md(d)
                recs = extract(metas[0])
                rec = recs[0]
                self.assertIsInstance(rec, dict)
                self.assertIn("content", rec)
        elif op == "nonexistent_root":
            self.assertEqual(scan_memory_md("/nonexistent_xyz/"), [])
        elif op == "empty_filemeta":
            with tempfile.TemporaryDirectory() as d:
                p = _w(d, "X/memory/t.md", "# T\nc")
                meta = FileMeta(path=p, name="t", project="", mtime=0.0, size=100)
                recs = extract(meta)
                rec = recs[0]
                self.assertIn("source", rec)
    return test

for c in TD.get("exception", []):
    setattr(TestException, f"test_{c['id']}", _mk_ex(c))


# ===== Regression =====

class TestRegression(_Base):
    _mod_name = "Regression"


def _mk_r(case):
    def test(self):
        _attach_case(self, case)
        op = case.get("op", "")
        if op == "cache_full_flow":
            with tempfile.TemporaryDirectory() as d:
                _w(d, "M/memory/a.md", "# A\nc")
                from src.scanner import scan_memory_md
                from src.extractor import extract
                from src import store as st
                meta = scan_memory_md(d)[0]
                cache = st.load_cache()
                self.assertTrue(st.needs_update(meta, cache))
                st.put_all(cache, meta, extract(meta))
                self.assertFalse(st.needs_update(meta, cache))
                os.utime(meta.path, (meta.mtime + 10, meta.mtime + 10))
                self.assertTrue(st.needs_update(scan_memory_md(d)[0], cache))
            return
        elif op == "reload_consistent":
            from src.keywords import reload, get_all_known_keywords
            b = len(get_all_known_keywords())
            reload()
            self.assertEqual(len(get_all_known_keywords()), b)
            return
        elif op == "graph_basic":
            from src.graph_view import build_graph_option
            records = [
                {"content": "A", "language": ["Python"], "type": "陷阱", "severity": "高", "tags": ["Python"], "platform": ["跨平台"]},
                {"content": "B", "language": ["Shell/Bash"], "type": "命令行", "severity": "中", "tags": ["Shell/Bash"], "platform": ["Linux"]},
            ]
            opt = build_graph_option(records, mode="network")
            self.assertEqual(len(opt["series"][0]["data"]), 2)
            return
        if "file" in case:
            from src.extractor import extract
            from src.scanner import scan_memory_md
            with tempfile.TemporaryDirectory() as d:
                path, content = case["file"][0], case["file"][1]
                _w(d, path, content)
                recs = extract(scan_memory_md(d)[0])
                rec = recs[0] if recs else {}
                exp = case["expected"]
                ok, msg = _ver(exp, rec)
                if not ok:
                    self.fail(msg)
            return
        if "files" in case:
            from src.scanner import scan_memory_md
            with tempfile.TemporaryDirectory() as d:
                _setup(d, case)
                self.assertEqual(len(scan_memory_md(d)), case["expected"]["count"])
            return
    return test

for c in TD.get("regression", []):
    setattr(TestRegression, f"test_{c['id']}", _mk_r(c))


# ===== Normalize =====

class TestNormalize(_Base):
    _mod_name = "Normalize"


def _mk_n(case):
    def test(self):
        _attach_case(self, case)
        from src.extractor import _normalize, _rule_extract_section
        from src.scanner import FileMeta
        from src import config as cfg
        from src.config import SCHEMA
        op = case["op"]
        if op == "normalize_defaults":
            meta = FileMeta(path="/tmp/n.md", name="n", project="P", mtime=0.0, size=10)
            rec = _normalize({}, meta, "raw")
            for f in SCHEMA:
                self.assertIn(f.key, rec)
        elif op == "normalize_preserve":
            meta = FileMeta(path="/tmp/p.md", name="p", project="P", mtime=0.0, size=10)
            rec = _normalize({"content": "custom", "language": ["Go"]}, meta, "raw")
            self.assertEqual(rec["content"], "custom")
        elif op == "normalize_truncated_true":
            meta = FileMeta(path="/tmp/t.md", name="t", project="P", mtime=0.0, size=cfg.READ_CHUNK_LIMIT)
            rec = _normalize({}, meta, "x" * cfg.READ_CHUNK_LIMIT)
            self.assertTrue(rec.get("_truncated"))
        elif op == "normalize_truncated_false":
            meta = FileMeta(path="/tmp/t.md", name="t", project="P", mtime=0.0, size=10)
            rec = _normalize({}, meta, "short")
            self.assertFalse(rec.get("_truncated"))
        elif op == "rule_extract_all":
            meta = FileMeta(path="/tmp/r.md", name="r", project="P", mtime=0.0, size=100)
            rec = _rule_extract_section("# Python\nc\n## 规避\nuse asyncio", "Python笔记", "", "")
            for key in ("content", "language", "platform", "type", "avoidance", "severity", "source", "tags"):
                self.assertIn(key, rec)
        elif op == "rule_extract_empty":
            meta = FileMeta(path="/tmp/e.md", name="e", project="P", mtime=0.0, size=0)
            rec = _rule_extract_section("", "", "", "")
            self.assertEqual(rec["language"], ["通用"])
            self.assertEqual(rec["platform"], ["跨平台"])
    return test

for c in TD.get("normalize", []):
    setattr(TestNormalize, f"test_{c['id']}", _mk_n(c))


# ===== 入口 =====

if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=0)
    result = runner.run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    _LOG.info("")
    _LOG.info("=" * 70)
    _LOG.info("═══ 测试结果汇总 ═══")
    total_all = 0
    total_fail = 0
    for mod, stats in sorted(_SUMMARY.items()):
        total_all += stats["total"]
        total_fail += stats["fail"] + stats["error"]
        if stats["fail"] + stats["error"] == 0:
            _LOG.info("  PASS  %-25s %3d 用例", mod, stats["total"])
        else:
            _LOG.error("  >>> FAIL <<<  %-25s %3d 用例 | PASS=%d FAIL=%d ERROR=%d",
                       mod, stats["total"], stats["pass"], stats["fail"], stats["error"])
    _LOG.info("───")
    if total_fail == 0:
        _LOG.info("  总计: %d 用例, 全部 PASS ✓", total_all)
    else:
        _LOG.error("  >>> 总计: %d 用例, %d 失败 <<<", total_all, total_fail)
    _LOG.info("=" * 70)
