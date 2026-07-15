# encoding: utf-8
"""MemoAlign 流水线单元测试（标准库 unittest，无第三方依赖）。

覆盖：scanner 发现、extractor 规则抽取（含 Shell/PowerShell/Batch/GitHub 场景）、
store 增量缓存、平台检测。
运行：python -m unittest tests.test_pipeline
"""
import os
import tempfile
import unittest

from src.scanner import scan_memory_md, FileMeta
from src.extractor import extract, _detect_platform, _detect_language, _detect_type
from src import store as store_mod


def _write(root: str, rel: str, text: str) -> None:
    """在临时根目录下写入文件。"""
    full = os.path.join(root, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(text)


class TestScanner(unittest.TestCase):
    """扫描器基础测试。"""

    def test_find_memory_md(self):
        """验证仅发现 memory 目录下的 md 文件。"""
        with tempfile.TemporaryDirectory() as d:
            _write(d, "A/memory/x.md", "# 标题\n内容")
            _write(d, "B/memory/y.md", "# 标题\n内容")
            _write(d, "C/notmemory/z.md", "# 标题\n内容")  # 不应被收录
            metas = scan_memory_md(d)
            self.assertEqual(len(metas), 2)
            self.assertTrue(all(m.name in ("x", "y") for m in metas))

    def test_empty_root(self):
        """验证空目录返回空列表。"""
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(scan_memory_md(d), [])


class TestExtractor(unittest.TestCase):
    """抽取器测试 —— 覆盖各语言/平台/类型场景。"""

    def test_rule_extract_python_trap(self):
        """Python 陷阱：语言检测 + 类型 + 规避方法。"""
        with tempfile.TemporaryDirectory() as d:
            _write(d, "P/memory/py.md",
                   "# Python 异步陷阱\n在协程中误用阻塞调用会出问题。\n"
                   "## 规避方法\n使用 asyncio.to_thread 包裹。")
            meta = scan_memory_md(d)[0]
            rec = extract(meta)
            self.assertIn("Python", rec["language"])
            self.assertEqual(rec["type"], "陷阱")
            self.assertIn("asyncio", rec["avoidance"])
            self.assertEqual(rec["source"], "P/py")
            self.assertIn("_raw", rec)
            self.assertIn("platform", rec)

    def test_shell_batch_cmd_detection(self):
        """Batch/CMD 场景：rmdir 命令 + 环境配置类型。"""
        with tempfile.TemporaryDirectory() as d:
            _write(d, "W/memory/cmd_issue.md",
                   "# 构建缓存清理\n构建前必须清 dist 文件夹 "
                   "（rmdir /s /q dist\\renderer），否则前端代码未更新。\n"
                   "## 规避方法\nPowerShell 用 Remove-Item -Recurse -Force。")
            meta = scan_memory_md(d)[0]
            rec = extract(meta)
            self.assertIn("Batch/CMD", rec["language"],
                          f"期望命中 Batch/CMD，实际: {rec['language']}")
            self.assertIn("PowerShell", rec["language"],
                          f"期望同时命中 PowerShell，实际: {rec['language']}")
            self.assertIn("Windows", rec["platform"],
                          f"期望命中 Windows 平台，实际: {rec['platform']}")

    def test_powershell_scenario(self):
        """PowerShell 场景：上传脚本 + 命令行类型。"""
        with tempfile.TemporaryDirectory() as d:
            _write(d, "E/memory/pwsh_release.md",
                   "# 上传发布脚本\n上传使用 _release.mjs (PowerShell版)，"
                   "需要先 Set-ExecutionPolicy RemoteSigned。\n"
                   "## 注意\n如果没有预留执行策略，PowerShell的 Out-File cmdlet 会报错。")
            meta = scan_memory_md(d)[0]
            rec = extract(meta)
            self.assertIn("PowerShell", rec["language"],
                          f"期望命中 PowerShell，实际: {rec['language']}")
            self.assertIn("JavaScript/TS", rec["language"],
                          f"期望同时命中 JS/TS (.mjs)，实际: {rec['language']}")

    def test_docker_scenario(self):
        """Docker 场景：compose + 环境配置类型。"""
        with tempfile.TemporaryDirectory() as d:
            _write(d, "D/memory/docker_setup.md",
                   "# Docker 环境搭建\n用 docker compose up 启动开发环境，"
                   "注意 dockerfile 基础镜像版本过老会导致pip install 失败。\n"
                   "## 解决方法\n改用 python:3.11-slim 并重新构建镜像。")
            meta = scan_memory_md(d)[0]
            rec = extract(meta)
            self.assertIn("Docker", rec["language"],
                          f"期望命中 Docker，实际: {rec['language']}")
            self.assertEqual(rec["type"], "环境配置",
                             f"期望类型=环境配置，实际: {rec['type']}")

    def test_git_github_scenario(self):
        """Git/GitHub 场景：gitignore + 命令行类型。"""
        with tempfile.TemporaryDirectory() as d:
            _write(d, "G/memory/git_hook.md",
                   "# Git 提交注意事项\n每次 commit 之前运行 pre-commit hook，"
                   "确保代码通过 lint 检查。如果有改动的文件不需要提交，"
                   "添加到 .gitignore 中。\n"
                   "## 注意\ngit push 之前先 git pull --rebase 避免冲突。")
            meta = scan_memory_md(d)[0]
            rec = extract(meta)
            self.assertIn("Git/GitHub", rec["language"],
                          f"期望命中 Git/GitHub，实际: {rec['language']}")
            # 含 "git"、"gitignore"、"commit" → 应命中 Git/GitHub

    def test_cross_platform_compatibility(self):
        """兼容性场景：编码/跨平台问题。"""
        with tempfile.TemporaryDirectory() as d:
            _write(d, "X/memory/encoding.md",
                   "# 跨平台换行符问题\nWindows 使用 CRLF，Linux 使用 LF，"
                   "git 在 Windows 上会转换换行符导致 diff 异常。\n"
                   "## 规避方法\n配置 git config --global core.autocrlf input。")
            meta = scan_memory_md(d)[0]
            rec = extract(meta)
            self.assertEqual(rec["type"], "兼容性",
                             f"期望类型=兼容性，实际: {rec['type']}")
            lang_set = set(rec["language"])
            self.assertTrue("Git/GitHub" in lang_set or "通用" in lang_set,
                            f"期望命中 Git/GitHub 或通用，实际: {rec['language']}")

    def test_platform_detection(self):
        """单元测 _detect_platform：独立验证平台检测逻辑。"""
        self.assertEqual(_detect_platform("在 Windows 上用 PowerShell 执行"),
                         ["Windows"])
        self.assertEqual(_detect_platform("使用 bash 在 Ubuntu 中运行"),
                         ["Linux"])
        self.assertEqual(_detect_platform("在 mac 终端用 brew 安装"),
                         ["macOS"])
        self.assertEqual(_detect_platform("这是一段通用 Python 代码"),
                         ["跨平台"])

    def test_language_detection_expanded(self):
        """验证新增语言范畴的关键词覆盖（单元测）。"""
        # Shell/Bash
        self.assertIn("Shell/Bash", _detect_language("bash 中运行 shell 脚本 .sh"))
        # PowerShell
        self.assertIn("PowerShell", _detect_language("powershell Exec set-executionpolicy"))
        # Batch/CMD
        self.assertIn("Batch/CMD", _detect_language("cmd 下用 rmdir 删除"))
        # Docker
        self.assertIn("Docker", _detect_language("docker compose up 创建容器"))
        # Git/GitHub
        self.assertIn("Git/GitHub", _detect_language("git commit 后 push 到 github"))

    def test_type_detection_expanded(self):
        """验证新增类型（命令行/环境配置/兼容性）的优先级命中。"""
        # 命令行优先于问题（"命令执行失败" 含 "执行失败"）
        self.assertEqual(_detect_type("命令执行失败需要退出码检查"),
                         "命令行")
        # 环境配置
        self.assertEqual(_detect_type("安装依赖时环境变量PATH未配置"),
                         "环境配置")
        # 兼容性
        self.assertEqual(_detect_type("跨平台编码gbk与utf-8编码问题"),
                         "兼容性")


class TestStore(unittest.TestCase):
    """缓存模块测试。"""

    def test_cache_invalidation(self):
        """验证缓存命中/失效逻辑（mtime 变化触发重抽）。"""
        with tempfile.TemporaryDirectory() as d:
            _write(d, "M/memory/a.md", "# A\n内容")
            meta = scan_memory_md(d)[0]
            cache = store_mod.load_cache()
            self.assertTrue(store_mod.needs_update(meta, cache))
            rec = extract(meta)
            store_mod.put(cache, meta, rec)
            self.assertFalse(store_mod.needs_update(meta, cache))
            # 改 mtime 触发重抽
            os.utime(meta.path, (meta.mtime + 10, meta.mtime + 10))
            meta2 = scan_memory_md(d)[0]
            self.assertTrue(store_mod.needs_update(meta2, cache))


if __name__ == "__main__":
    unittest.main()
