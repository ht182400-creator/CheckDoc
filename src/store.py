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
    path = _cache_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("缓存结构异常")
        return data
    except Exception as exc:
        log.warning("缓存读取失败，将重建: %s | %s", path, exc)
        return {}


def needs_update(meta: FileMeta, cache: Dict[str, dict]) -> bool:
    """判断文件是否需要重新抽取（缓存缺失或 mtime 变化）。"""
    entry = cache.get(meta.path)
    if entry is None:
        return True
    return entry.get("__mtime") != meta.mtime


def save_cache(cache: Dict[str, dict]) -> None:
    """持久化缓存（异常隔离，失败仅告警）。"""
    path = _cache_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        log.error("缓存写入失败: %s\n%s", exc, traceback.format_exc())


# 预览文本最大字符数（缓存时截断 _raw 以瘦身，详情有需可从文件重读）
RAW_PREVIEW_LEN: int = 2000


def put(cache: Dict[str, dict], meta: FileMeta, record: dict) -> None:
    """将抽取结果写入缓存（去除 _raw 全文，仅保留预览以瘦身）。"""
    payload = {k: v for k, v in record.items() if k != "_raw"}
    # 保留截断预览供缓存命中时快速展示（完整原文需重新扫描时从文件读取）
    payload["_raw_preview"] = record.get("_raw", "")[:RAW_PREVIEW_LEN]
    payload["__mtime"] = meta.mtime
    cache[meta.path] = payload


def reset() -> None:
    """清空缓存文件（强制全量重扫）。"""
    path = _cache_path()
    if os.path.exists(path):
        try:
            os.remove(path)
            log.info("缓存已清空: %s", path)
        except OSError as exc:
            log.warning("清空缓存失败: %s", exc)
