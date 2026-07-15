# encoding: utf-8
"""增量缓存：基于 path + mtime 的抽取结果缓存，加速重扫。"""
import json
import os
import traceback
from typing import Dict, List

from . import config
from .logger import log
from .scanner import FileMeta


def _cache_path() -> str:
    """返回缓存文件绝对路径（确保目录存在）。"""
    os.makedirs(config.CACHE_DIR, exist_ok=True)
    return os.path.join(config.CACHE_DIR, config.CACHE_FILE)


def load_cache() -> Dict[str, dict]:
    """加载缓存；文件损坏/不存在时返回空字典（自动重建）。"""
    log.debug("load_cache 入口")
    path = _cache_path()
    if not os.path.exists(path):
        log.debug("load_cache 出口 | 缓存文件不存在 -> {}")
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("缓存结构异常")
        log.debug("load_cache 出口 | 条目数=%d", len(data))
        return data
    except Exception as exc:
        log.warning("缓存读取失败，将重建: %s | %s", path, exc)
        log.debug("load_cache 出口(异常) | -> {}")
        return {}


def needs_update(meta: FileMeta, cache: Dict[str, dict]) -> bool:
    """判断文件是否需要重新抽取（缓存缺失或 mtime 变化）。"""
    log.debug("needs_update 入口 | path=%s, mtime=%.0f", meta.path, meta.mtime)
    entry = cache.get(meta.path)
    if entry is None:
        log.debug("needs_update 出口 | 缓存缺失 -> True")
        return True
    # 兼容新旧缓存格式
    need = entry.get("__mtime") != meta.mtime
    log.debug("needs_update 出口 | mtime变化=%s -> %s", need, need)
    return need


def get_cached_records(meta: FileMeta, cache: Dict[str, dict]) -> list:
    """从缓存中取出一个文件的所有记录（兼容新旧格式）。"""
    entry = cache.get(meta.path)
    if entry is None:
        return []
    # 新格式：{"__mtime": ..., "records": [...]}
    if "records" in entry:
        recs = entry["records"]
        for rec in recs:
            rec.pop("__mtime", None)  # 去掉内部标记
        return recs
    # 旧格式：单条记录
    rec = {k: v for k, v in entry.items() if k not in ("__mtime",)}
    return [rec] if rec else []


def save_cache(cache: Dict[str, dict]) -> None:
    """持久化缓存（异常隔离，失败仅告警）。"""
    log.debug("save_cache 入口 | 条目数=%d", len(cache))
    path = _cache_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        log.debug("save_cache 出口 | 写入成功, path=%s", path)
    except Exception as exc:
        log.error("缓存写入失败: %s\n%s", exc, traceback.format_exc())


# 预览文本最大字符数（缓存时截断 _raw 以瘦身，详情有需可从文件重读）
RAW_PREVIEW_LEN: int = 2000


def put_all(cache: Dict[str, dict], meta: FileMeta, records: list) -> None:
    """将一个文件的多条抽取结果写入缓存（去除 _raw，仅保留预览）。"""
    slim_records = []
    for rec in records:
        slim = {k: v for k, v in rec.items() if k != "_raw"}
        slim["_raw_preview"] = rec.get("_raw", "")[:RAW_PREVIEW_LEN]
        slim_records.append(slim)
    cache[meta.path] = {
        "__mtime": meta.mtime,
        "records": slim_records,
    }


def put(cache: Dict[str, dict], meta: FileMeta, record: dict) -> None:
    """将单条抽取结果写入缓存（兼容旧调用，内部转多条）。"""
    put_all(cache, meta, [record])


def reset() -> None:
    """清空缓存文件（强制全量重扫）。"""
    path = _cache_path()
    if os.path.exists(path):
        try:
            os.remove(path)
            log.info("缓存已清空: %s", path)
        except OSError as exc:
            log.warning("清空缓存失败: %s", exc)
