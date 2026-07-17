# encoding: utf-8
"""MemoAlign 循环工程：一键验证脚本（供验证子代理独立运行）。

做什么：
    1. 编译检查 src/*.py
    2. 运行 unittest 回归（test_pipeline + test_runner）
    3. 输出人类可读报告 + 机器可读 JSON（tests/loop_verify.json）
    4. 有任一失败则 exit(1)，全过 exit(0)

用法：
    python loop/verify.py
验证子代理应独立运行本脚本并对结果做"通过/未通过"判定，不信任执行代理的自述。
"""
import ast
import json
import os
import subprocess
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _sp(text: str) -> None:
    """安全打印：按控制台编码（通常 GBK）输出，无法编码的字符替换为 ?。"""
    enc = (sys.stdout.encoding or "gbk").lower()
    safe = text.encode(enc, errors="replace").decode(enc, errors="replace")
    print(safe)


def _run(cmd: list) -> dict:
    """运行子命令，返回 {ok, rc, out}。以字节捕获避免 GBK/UTF-8 混用崩溃。"""
    try:
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True)
        out = (proc.stdout or b"") + (proc.stderr or b"")
        return {
            "ok": proc.returncode == 0,
            "rc": proc.returncode,
            "out": out.decode("utf-8", errors="replace")[-4000:],
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "rc": -1, "out": f"{exc}\n{traceback.format_exc()}"}


def _check_ui_import() -> dict:
    """UI 模块导入冒烟（W1 拆分后防止循环导入 / 重命名遗漏导致应用无法启动）。"""
    return _run([sys.executable, "-c", "import src.ui_app"])


def _check_case_library() -> dict:
    """W13 静态检查：每个 tests/test_*.py 中的 test_* 方法必须在 docs/09 登记。

    防止"新增测试未同步案例库"或"案例数造假"。用 AST 抽取
    `ClassName.method` 全限定名，要求其在 docs/09_测试案例库.md 中出现。
    """
    doc_path = os.path.join(ROOT, "docs", "09_测试案例库.md")
    if not os.path.exists(doc_path):
        return {"ok": False, "out": "docs/09_测试案例库.md 缺失"}
    with open(doc_path, "r", encoding="utf-8") as f:
        doc_text = f.read()
    test_dir = os.path.join(ROOT, "tests")
    missing = []
    try:
        for fn in sorted(os.listdir(test_dir)):
            if not fn.startswith("test_") or not fn.endswith(".py"):
                continue
            path = os.path.join(test_dir, fn)
            with open(path, "r", encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    for sub in node.body:
                        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                                and sub.name.startswith("test_"):
                            ref = f"{node.name}.{sub.name}"
                            if ref not in doc_text:
                                missing.append(f"{fn}:{ref}")
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "out": f"解析测试文件失败: {exc}\n{traceback.format_exc()}"}
    if missing:
        return {"ok": False, "out": "以下测试用例未在 docs/09 登记:\n" + "\n".join(missing)}
    return {"ok": True, "out": ""}


def main() -> int:
    report = {"compile": {}, "ui_import": {}, "case_library": {}, "tests": {}, "passed": False}
    print("=" * 60)
    print("MemoAlign verify - compile + test")
    print("=" * 60)

    # 1) 编译检查
    comp = _run([sys.executable, "-m", "py_compile", *[
        os.path.join("src", f) for f in os.listdir(os.path.join(ROOT, "src")) if f.endswith(".py")
    ]])
    report["compile"] = {"ok": comp["ok"], "rc": comp["rc"]}
    print(f"[compile] {'PASS' if comp['ok'] else 'FAIL'} (rc={comp['rc']})")
    if not comp["ok"]:
        _sp(comp["out"])

    # 2) UI 模块导入冒烟（W1 拆分后回归）
    ui_imp = _check_ui_import()
    report["ui_import"] = {"ok": ui_imp["ok"], "rc": ui_imp["rc"]}
    print(f"[ui_import] {'PASS' if ui_imp['ok'] else 'FAIL'} (rc={ui_imp['rc']})")
    if not ui_imp["ok"]:
        _sp(ui_imp["out"])

    # 3) 案例库同步静态检查（W13 阻断项）
    cl = _check_case_library()
    report["case_library"] = {"ok": cl["ok"]}
    print(f"[case_library] {'PASS' if cl['ok'] else 'FAIL'}")
    if not cl["ok"]:
        _sp(cl["out"])

    # 4) 测试
    for suite in ("tests.test_pipeline", "tests.test_runner", "tests.test_quality",
                  "tests.test_sync", "tests.test_highlight", "tests.test_ui_helpers",
                  "tests.test_exporters", "tests.test_record_edit"):
        t = _run([sys.executable, "-m", "unittest", suite, "-v"])
        report["tests"][suite] = {"ok": t["ok"], "rc": t["rc"]}
        print(f"[{suite}] {'PASS' if t['ok'] else 'FAIL'} (rc={t['rc']})")
        if not t["ok"]:
            _sp(t["out"][-2500:])

    report["passed"] = (
        comp["ok"] and ui_imp["ok"] and cl["ok"]
        and all(v["ok"] for v in report["tests"].values())
    )
    out_path = os.path.join(ROOT, "tests", "loop_verify.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print("-" * 60)
    print(f"verdict: {'ALL PASS' if report['passed'] else 'HAS FAILURE'}")
    print(f"report -> {out_path}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
