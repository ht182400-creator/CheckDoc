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


def main() -> int:
    report = {"compile": {}, "tests": {}, "passed": False}
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

    # 2) 测试
    for suite in ("tests.test_pipeline", "tests.test_runner"):
        t = _run([sys.executable, "-m", "unittest", suite, "-v"])
        report["tests"][suite] = {"ok": t["ok"], "rc": t["rc"]}
        print(f"[{suite}] {'PASS' if t['ok'] else 'FAIL'} (rc={t['rc']})")
        if not t["ok"]:
            _sp(t["out"][-2500:])

    report["passed"] = comp["ok"] and all(v["ok"] for v in report["tests"].values())
    out_path = os.path.join(ROOT, "tests", "loop_verify.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print("-" * 60)
    print(f"verdict: {'ALL PASS' if report['passed'] else 'HAS FAILURE'}")
    print(f"report -> {out_path}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
