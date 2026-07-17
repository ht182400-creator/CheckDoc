# encoding: utf-8
"""UI 纯函数辅助层（无界面副作用，可单测）。

包含：表格列生成、记录扁平化、记录查找、时间范围判定、chips 渲染、
highlight.js 注入头。除 `_render_chips`（需要 NiceGUI 控件）外，其余函数
不依赖 `nicegui`，便于 `tests/test_ui_helpers.py` 直接单测。
"""
from typing import Dict, List, Optional

from . import config
from . import scanner
from . import _ui_state as S
from .config import FieldType
from .logger import log


# P2-4：详情页代码高亮（highlight.js via CDN；离线时优雅降级为纯文本代码块）
HIGHLIGHT_HEAD_HTML = (
    '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/'
    f'highlight.js@{config.HIGHLIGHTJS_CDN_VERSION}/styles/{{theme}}.min.css">'
    .replace("{theme}", config.CODE_HIGHLIGHT_THEME)
    + '<script src="https://cdn.jsdelivr.net/npm/'
    f'highlight.js@{config.HIGHLIGHTJS_CDN_VERSION}/lib/highlight.min.js"></script>'
)


def _build_columns() -> List[Dict]:
    """由 SCHEMA 生成 Quasar 表格列定义（可排序 + 宽度/省略样式）。"""
    cols = []
    for f in config.SCHEMA:
        col = {
            "name": f.key,
            "label": f.label,
            "field": f.key,
            "sortable": True,
            "align": "left",
        }
        if f.width != "auto":
            col["headerStyle"] = f"width:{f.width};"
            col["style"] = f"width:{f.width};"
        if f.ftype == FieldType.TEXT:
            # 文本列自动换行，显示完整内容（行高自适应）
            col["style"] = (col.get("style", "") +
                            "max-width:400px;overflow-wrap:break-word;"
                            "white-space:normal;")
        cols.append(col)
    # P2-2：质量分列（非 Schema 字段，单独追加，带等级徽标）
    cols.append({
        "name": config.QUALITY_SCORE_KEY,
        "label": "质量分",
        "field": config.QUALITY_SCORE_KEY,
        "sortable": True,
        "align": "left",
        "headerStyle": "width:90px;",
        "style": "width:90px;",
    })
    return cols


def _find_record_by_id(rid) -> Optional[Dict]:
    """按 id 在全局 records 中查找原记录对象（就地修改用）。"""
    for r in S.records:
        if r.get("id") == rid:
            return r
    return None


def _flatten_records(rows: List[Dict]) -> List[Dict]:
    """将所有 MULTI 字段（list）转为逗号字符串（不改原数据），避免 Quasar 表格崩溃。"""
    multi_keys = {f.key for f in config.SCHEMA if f.ftype == FieldType.MULTI}
    result = []
    for row in rows:
        copy = dict(row)
        for key in multi_keys:
            val = copy.get(key)
            if isinstance(val, list):
                copy[key] = ", ".join(str(x) for x in val)
        result.append(copy)
    return result


def record_within_time_range(r: Dict, days: int) -> bool:
    """判断记录是否在最近 days 天的范围内（W8 可单测）。

    days <= 0 表示不限；记录无 _mtime 时视为通过（避免误过滤历史数据）。
    """
    if days <= 0:
        return True
    mtime_val = r.get("_mtime", 0)
    if not mtime_val:
        return True
    import time
    cutoff = time.time() - days * config.SECONDS_PER_DAY
    return mtime_val >= cutoff


def _render_chips(container, counts: Dict[str, int], max_n: int, color_map: Dict[str, str]) -> None:
    """在给定容器里渲染 chips（依赖 NiceGUI 控件）。"""
    from nicegui import ui  # 延迟导入，保持本模块其余函数可脱离 UI 单测
    container.clear()
    with container:
        if not counts:
            ui.chip("（无数据）", removable=False, color="grey").props("dense")
            return
        # 按 count 降序，取前 max_n
        top = sorted(counts.items(), key=lambda x: -x[1])[:max_n]
        for name, cnt in top:
            color = color_map.get(name, "primary")
            chip = ui.chip(f"{name} · {cnt}", removable=False, color=color)
            chip.props("dense square")
