# encoding: utf-8
"""记录内编辑（P3）：将用户编辑写回记录并重算质量分 / 低分定位。

设计：
- 纯逻辑（不依赖 NiceGUI），便于单测；UI 层负责采集控件值与刷新。
- merge_edit 仅覆盖 Schema 字段，保留 _path/_raw/id 等内部字段。
- next_low_score 用于"修正低分"流程：返回首个低分或"未评分"记录。
"""
from typing import Dict, List, Optional

from . import config


def merge_edit(record: Dict, edited: Dict, schema) -> Dict:
    """将用户编辑（字段 key -> 值）写回 record。

    Args:
        record: 内存中的原始记录（就地修改并返回）
        edited: 各字段新值（key 对应 SCHEMA.key）
        schema: config.SCHEMA 字段定义列表

    Returns:
        Dict: 同一 record 对象（已写入新字段）
    """
    for f in schema:
        if f.key in edited:
            record[f.key] = edited[f.key]
    return record


def is_low_score(record: Dict, threshold: Optional[int] = None) -> bool:
    """判断记录是否为低分（分数 < threshold）或"未评分"（None）。"""
    if threshold is None:
        threshold = config.QUALITY_MID_THRESHOLD
    s = record.get(config.QUALITY_SCORE_KEY)
    if not isinstance(s, int):
        return True  # 未评分视为待修正
    return s < threshold


def next_low_score(records: List[Dict], threshold: Optional[int] = None) -> Optional[Dict]:
    """返回列表中第一条低分/未评分记录；无则 None。"""
    for r in records:
        if is_low_score(r, threshold):
            return r
    return None
