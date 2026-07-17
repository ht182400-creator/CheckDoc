# encoding: utf-8
"""通过 GitHub REST API 推送本地代码到远程仓库（无需 git push）。

Loop Engineering 连接器：自动化每轮迭代验证通过后调用本脚本推送并打 tag。
因本机 `git push` 常因网络 reset 失败，统一走 GitHub API。

用法：
    python _gh_push.py <version> [commit_message]
    # token 从环境变量 GITHUB_TOKEN 读取（已在环境中配置）

示例：
    python _gh_push.py v0.0.4 "v0.0.4: 修复测试债务，loop/verify.py 全绿"
"""
import json
import os
import sys
import urllib.request
import urllib.error

OWNER = "ht182400-creator"
REPO = "CheckDoc"
API_BASE = "https://api.github.com"

# 排除项：不纳入推送的目录 / 文件
EXCLUDE_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", "dist", "build",
                ".cache", ".pytest_cache"}
EXCLUDE_SUFFIX = (".pyc", ".log")
# 仓库根目录下的临时/调试文件
ROOT_TEMP = {"_add_debug.py", "_test_multi.py", "_test_out.txt", "_server.log", "_server_err.log"}
# tests/ 下的临时产物（诊断脚本、临时 txt、运行日志）
TESTS_TEMP_PREFIX = ("_",)        # tests/_xxx.py / tests/_xxx.txt
TESTS_LOG_PREFIX = ("test_run_",)  # tests/test_run_*.log


def _should_exclude(rel: str) -> bool:
    """判断相对路径是否应被排除（用于收集与远程删除）。"""
    if rel.startswith(".git/"):
        return True
    parts = rel.split("/")
    if any(p in EXCLUDE_DIRS for p in parts):
        return True
    fn = parts[-1]
    if fn.endswith(EXCLUDE_SUFFIX):
        return True
    # 轮转日志：MemoAlign.log / MemoAlign.log.2026-07-15
    if fn == "MemoAlign.log" or fn.startswith("MemoAlign.log."):
        return True
    if rel in ROOT_TEMP:
        return True
    if rel.startswith("tests/"):
        if fn.startswith(TESTS_TEMP_PREFIX) or fn.startswith(TESTS_LOG_PREFIX):
            return True
    return False


def _collect_files(root: str):
    """遍历仓库，返回 [(相对路径posix, 绝对路径)]，排除临时/构建产物。"""
    out = []
    for dp, dnames, fnames in os.walk(root):
        dnames[:] = [d for d in dnames if d not in EXCLUDE_DIRS]
        for fn in fnames:
            full = os.path.join(dp, fn)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if _should_exclude(rel):
                continue
            if os.path.isfile(full):
                out.append((rel, full))
    # 稳定排序，保证每次推送一致
    out.sort(key=lambda x: x[0])
    return out


def _collect_deletions(token, base_tree_sha, keep_set):
    """获取远程 base tree，返回应删除的条目（日志/缓存等被排除文件）。

    返回形如 [{"path":..., "mode":"100644","type":"blob","sha":None}] 的删除项；
    若获取失败则返回空列表（不影响主流程）。
    """
    code, tree = _api("GET", f"/repos/{OWNER}/{REPO}/git/trees/{base_tree_sha}?recursive=1", token)
    if code != 200:
        return []
    dels = []
    for item in tree.get("tree", []):
        if item.get("type") != "blob":
            continue
        p = item["path"]
        if p in keep_set or not _should_exclude(p):
            continue
        # 远程存在但本地应排除 → 删除
        dels.append({"path": p, "mode": "100644", "type": "blob", "sha": None})
    return dels


def _api(method, path, token, body=None):
    """调用 GitHub REST API，返回 (status, data)。"""
    url = f"{API_BASE}{path}"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8") if exc.fp else ""
        try:
            err_json = json.loads(err_body) if err_body else {}
        except ValueError:
            err_json = err_body
        return exc.code, err_json


def get_latest_commit_sha(token):
    """获取远程 master 分支最新 commit SHA。"""
    code, data = _api("GET", f"/repos/{OWNER}/{REPO}/git/ref/heads/master", token)
    if code == 200:
        return data["object"]["sha"]
    raise RuntimeError(f"获取 master ref 失败: {code} {data}")


def create_tag(token, sha, tag_name, move=False):
    """通过 API 创建 tag ref。move=True 时若已存在则先删除再重建（幂等）。"""
    ref_name = f"refs/tags/{tag_name}"
    if move:
        _api("DELETE", f"/repos/{OWNER}/{REPO}/git/refs/tags/{tag_name}", token)
    code, data = _api("POST", f"/repos/{OWNER}/{REPO}/git/refs", token, {
        "ref": ref_name,
        "sha": sha,
    })
    if code == 201:
        return data["ref"]
    if code == 422 and "already exists" in str(data):
        print(f"  Tag {tag_name} 已存在，跳过")
        return ref_name
    raise RuntimeError(f"创建 tag 失败: {code} {data}")


def push_commit_via_api(token, files, commit_msg):
    """通过 API 推送多个文件到 master 分支（创建新 commit）。

    流程：GET master SHA → 为每个文件创建 blob → 创建 tree → 创建 commit → 更新 master ref。
    """
    master_sha = get_latest_commit_sha(token)
    code, commit_data = _api("GET", f"/repos/{OWNER}/{REPO}/git/commits/{master_sha}", token)
    if code != 200:
        raise RuntimeError(f"获取 commit 详情失败: {code} {commit_data}")
    base_tree_sha = commit_data["tree"]["sha"]
    print(f"  远程 master SHA: {master_sha[:7]}, tree: {base_tree_sha[:7]}")

    tree_items = []
    keep_set = set()
    for path, abs_path in files:
        with open(abs_path, "r", encoding="utf-8") as f:
            content = f.read()
        code, blob = _api("POST", f"/repos/{OWNER}/{REPO}/git/blobs", token, {
            "content": content,
            "encoding": "utf-8",
        })
        if code != 201:
            raise RuntimeError(f"创建 blob 失败 ({path}): {code} {blob}")
        tree_items.append({
            "path": path.replace("\\", "/"),
            "mode": "100644",
            "type": "blob",
            "sha": blob["sha"],
        })
        keep_set.add(path.replace("\\", "/"))
        print(f"  blob: {path} ({len(content)} bytes)")

    # 清理远程已存在的冗余文件（日志/缓存等本地应排除项）
    deletions = _collect_deletions(token, base_tree_sha, keep_set)
    if deletions:
        print(f"  清理远程冗余文件: {len(deletions)} 个")
        for d in deletions:
            print(f"    删除: {d['path']}")
        tree_items = tree_items + deletions

    try:
        code, tree = _api("POST", f"/repos/{OWNER}/{REPO}/git/trees", token, {
            "base_tree": base_tree_sha,
            "tree": tree_items,
        })
        if code != 201:
            raise RuntimeError(f"创建 tree 失败: {code} {tree}")
    except Exception:
        # 若删除项导致 tree 创建失败（API 不接受 sha=null），退回仅新增/更新
        if deletions:
            print("  [warn] 含删除项的 tree 创建失败，退回仅新增/更新模式")
            tree_items = [t for t in tree_items if t.get("sha") is not None]
            code, tree = _api("POST", f"/repos/{OWNER}/{REPO}/git/trees", token, {
                "base_tree": base_tree_sha,
                "tree": tree_items,
            })
            if code != 201:
                raise RuntimeError(f"创建 tree 失败: {code} {tree}")
        else:
            raise

    print(f"  tree: {tree['sha'][:7]}")

    code, new_commit = _api("POST", f"/repos/{OWNER}/{REPO}/git/commits", token, {
        "message": commit_msg,
        "tree": tree["sha"],
        "parents": [master_sha],
    })
    if code != 201:
        raise RuntimeError(f"创建 commit 失败: {code} {new_commit}")
    new_sha = new_commit["sha"]
    print(f"  commit: {new_sha[:7]}")

    code, _ = _api("PATCH", f"/repos/{OWNER}/{REPO}/git/refs/heads/master", token, {
        "sha": new_sha,
        "force": False,
    })
    if code != 200:
        raise RuntimeError(f"更新 master ref 失败: {code}")
    print(f"  master ref 已更新 → {new_sha[:7]}")
    return new_sha


def main():
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print("错误：未找到环境变量 GITHUB_TOKEN")
        print("请先设置: $env:GITHUB_TOKEN = '<your_token>'")
        sys.exit(1)

    version = sys.argv[1] if len(sys.argv) > 1 else "v0.0.4"
    if not version.startswith("v"):
        version = f"v{version}"
    commit_msg = sys.argv[2] if len(sys.argv) > 2 else f"{version}: 自动迭代（Loop Engineering）"

    print(f"=== GitHub API 推送 {version}: {OWNER}/{REPO} ===\n")

    root = os.path.dirname(os.path.abspath(__file__))
    files = _collect_files(root)
    print(f"  待推送文件数: {len(files)}\n")

    try:
        new_sha = push_commit_via_api(token, files, commit_msg)
        print(f"\n  创建 tag {version} ...")
        create_tag(token, new_sha, version, move=True)
        print(f"\n[OK] 推送成功: https://github.com/{OWNER}/{REPO}")
        print(f"[OK] 版本: {version}  commit: {new_sha[:7]}")
    except Exception as exc:
        print(f"\n[FAIL] {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
