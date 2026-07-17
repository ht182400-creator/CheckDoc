# encoding: utf-8
"""定时增量同步（P2-3）：对比两次扫描结果，产出新增/变更/移除的差异。

用法：
    from . import sync
    diff = sync.compute_diff(old_records, new_records)
    # diff = {"added":[...], "changed":[...], "removed":[...]}

设计：
- 以记录 _path 为主键（同文件多条记录按文件聚合）。
- 同路径下比较 _mtime 判定"变更"（文件被改动 → 需重抽）。
- 完全离线、无副作用，供 UI 定时器或手动按钮调用。
"""
from typing import Dict, List


def _path_index(records: List[dict]) -> Dict[str, dict]:
    """构建 _path -> 记录 的索引（同路径多条取最后一条作为代表）。"""
    idx: Dict[str, dict] = {}
    for r in records:
        if not isinstance(r, dict):
            continue
        p = r.get("_path")
        if p:
            idx[p] = r
    return idx


def compute_diff(old_records: List[dict], new_records: List[dict]) -> Dict[str, List[dict]]:
    """对比新旧记录，返回新增/变更/移除三类差异。

    Args:
        old_records: 上一次扫描得到的记录列表
        new_records: 本次扫描得到的记录列表

    Returns:
        Dict: {"added": 新出现的记录, "changed": mtime 变化的记录（取新值）,
               "removed": 消失的记录}
    """
    old_idx = _path_index(old_records)
    new_idx = _path_index(new_records)
    added = [r for p, r in new_idx.items() if p not in old_idx]
    removed = [r for p, r in old_idx.items() if p not in new_idx]
    changed = [
        r for p, r in new_idx.items()
        if p in old_idx and old_idx[p].get("_mtime") != r.get("_mtime")
    ]
    return {"added": added, "changed": changed, "removed": removed}


def summarize(diff: Dict[str, List[dict]]) -> str:
    """将差异汇总为一句人类可读文案。"""
    return (f"新增 {len(diff.get('added', []))} · "
            f"变更 {len(diff.get('changed', []))} · "
            f"移除 {len(diff.get('removed', []))}")
