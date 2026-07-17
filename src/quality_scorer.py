# encoding: utf-8
"""LLM 质量评分（P2-2）：对抽取记录打分（0-100），衡量完整度/可信度。

设计：
- 双模式：离线 heuristic（基于字段完整度，无需网络/密钥，始终可用）；
  LLM 模式（启用且有密钥时调用 LLM 综合语义打分，更准确）。
- LLM 失败自动回落 heuristic，保证整体稳定。
- 评分结果写入记录字段 config.QUALITY_SCORE_KEY，随缓存持久化。
"""
import os
from typing import Dict, List, Optional

from . import config
from .logger import log


def tier_of(score: Optional[int]) -> str:
    """将分数映射为等级文字（None/缺失 → 未评分）。"""
    if score is None:
        return config.QUALITY_TIER_NONE
    if score >= config.QUALITY_HIGH_THRESHOLD:
        return config.QUALITY_TIER_HIGH
    if score >= config.QUALITY_MID_THRESHOLD:
        return config.QUALITY_TIER_MID
    return config.QUALITY_TIER_LOW


def heuristic_score(record: Dict) -> int:
    """离线启发式评分：依据字段完整度累加（满分详见 QUALITY_FULL_SCORE）。

    维度（权重来自 config 命名常量）：
    内容 + 规避方法 + 严重度 + 语言已匹配 + 类型非"其他" + 标签。
    """
    score = 0
    if (record.get("content") or "").strip():
        score += config.QUALITY_WEIGHT_CONTENT
    if (record.get("avoidance") or "").strip():
        score += config.QUALITY_WEIGHT_AVOIDANCE
    if record.get("severity") in config.SEVERITY_OPTIONS:
        score += config.QUALITY_WEIGHT_SEVERITY
    langs = record.get("language") or []
    if langs and langs != ["通用"]:
        score += config.QUALITY_WEIGHT_LANGUAGE
    typ = record.get("type")
    if typ and typ not in ("其他", None, ""):
        score += config.QUALITY_WEIGHT_TYPE
    if record.get("tags"):
        score += config.QUALITY_WEIGHT_TAGS
    return min(score, config.QUALITY_FULL_SCORE)


def _llm_score(record: Dict) -> int:
    """调用 LLM 对单条记录打分；失败抛异常交由 score_record 回落。"""
    from .llm_client import LLMExtractor  # 延迟导入避免循环依赖
    client = LLMExtractor()
    return client.score(record)


def score_record(record: Dict, llm: bool = False) -> int:
    """对单条记录打分；llm=True 且可用时走 LLM，否则/H失败回落 heuristic。"""
    if llm and config.LLM_ENABLED and (config.LLM_API_KEY or os.environ.get("MEMOALIGN_LLM_API_KEY")):
        try:
            s = _llm_score(record)
            log.debug("LLM 质量评分成功: score=%s", s)
            return max(0, min(config.QUALITY_FULL_SCORE, s))
        except Exception as exc:
            log.warning("LLM 质量评分失败，回落 heuristic: %s", exc)
    return heuristic_score(record)


def score_records(records: List[Dict], llm: bool = False) -> None:
    """就地为所有记录写入 quality_score（不返回值，便于缓存持久化）。"""
    for r in records:
        if not isinstance(r, dict):
            continue
        r[config.QUALITY_SCORE_KEY] = score_record(r, llm=llm)
