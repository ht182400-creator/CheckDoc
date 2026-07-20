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

# 预计算字段键集合（避免每次 flatten 都遍历 SCHEMA）
_MULTI_FIELD_KEYS = {f.key for f in config.SCHEMA if f.ftype == FieldType.MULTI}
_TEXT_FIELD_KEYS = {f.key for f in config.SCHEMA if f.ftype == FieldType.TEXT}
# 不推送到前端表格的内部大字段：详情/导出按 id 从服务端 S.records 现取
_DISPLAY_EXCLUDE_KEYS = ("_raw", "_raw_preview")


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


def _parse_row_click_id(args) -> Optional[int]:
    """从 rowClick 事件参数中解析出记录 id（供打开详情）。

    - 注册时已显式 args=["row"]，故 args 即 row dict，直接取 "id"。
    - 防御：若历史/异常情况下 args 为 Quasar 整包列表 [evt, row, pageIndex]，
      或根本不是 dict，返回 None（不崩溃，避免 'list' object has no attribute 'get'）。
    """
    if isinstance(args, dict):
        rid = args.get("id")
        return rid if isinstance(rid, int) else None
    # 误传列表/非 dict：安全跳过
    return None


def _flatten_one(row: Dict) -> Dict:
    """单条记录转为前端显示行：MULTI→字符串、TEXT 超长截断预览、剔除内部大字段。

    显示行只含轻量字段（不携整篇原文），完整数据留服务端 S.records；
    详情按 id 现取、导出读完整可见记录，避免大表 WebSocket 推送撑爆缓冲（治本）。
    """
    copy = dict(row)
    # 1) 文本字段超长截断为预览（完整内容由详情/导出按需取）
    for key in _TEXT_FIELD_KEYS:
        val = copy.get(key)
        if isinstance(val, str) and len(val) > config.CONTENT_PREVIEW_MAX:
            copy[key] = val[:config.CONTENT_PREVIEW_MAX] + "…"
    # 2) 剔除不展示的内部大字段（_raw 整篇原文 / _raw_preview 缓存预览）
    for key in _DISPLAY_EXCLUDE_KEYS:
        copy.pop(key, None)
    # 3) MULTI 字段列表→逗号字符串（Quasar 表格不接 list）
    for key in _MULTI_FIELD_KEYS:
        val = copy.get(key)
        if isinstance(val, list):
            copy[key] = ", ".join(str(x) for x in val)
    return copy


def _flatten_records(rows: List[Dict]) -> List[Dict]:
    """将记录列表转为前端表格显示行（MULTI 转字符串、TEXT 截断、剔除 _raw）。

    显示行只含轻量字段，完整数据留服务端 S.records；详情按 id 现取、导出读
    完整可见记录，避免整篇原文经 WebSocket 推送撑爆缓冲（治本去 O(N²)）。
    """
    return [_flatten_one(r) for r in rows]


def _flatten(v) -> str:
    """列表/标量统一为可检索/可写入的字符串（全文检索共用，语义对齐 exporters.flatten）。

    原 ui_app.py 依赖 `exporters.flatten` 做跨字段全文检索；拆分后将单值语义收敛到本函数，
    避免 UI 层直接 import exporters。列表用 ``; `` 连接，None 转空串，其余转 str。
    """
    if isinstance(v, list):
        return "; ".join(str(x) for x in v)
    return "" if v is None else str(v)


def _normalize_search_text(s) -> str:
    """全文检索归一化：小写 + 去除全部空白（空格/全角空格/换行/制表）。

    解决中英文拼接处的空白导致漏匹配，例如记录原文「向导 App …」与用户输入
    「向导app」应视为匹配。空白归一化对双方同时生效，故「向导 App」会折叠为
    「向导app」、与查询词一致。用于全局检索与列关键字筛选（P1-1 修复）。
    """
    if s is None:
        return ""
    return "".join(str(s).lower().split())


def _resolve_export_scope() -> str:
    """解析导出范围下拉值（纯函数，便于单测）。

    - 下拉为 "all" → 返回 "all"（导出全部记录，忽略筛选）；
    - 其余（含下拉为 None/未初始化）→ 回落 "visible"（当前可见 = 按筛选结果）。
    """
    val = S.export_scope.value if S.export_scope is not None else None
    return "all" if val == "all" else "visible"


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
