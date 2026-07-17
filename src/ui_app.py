# encoding: utf-8
"""NiceGUI 界面：路径输入、扫描、统计、筛选栏、交互表格、详情、导出。

设计要点：
- 表格列/筛选器由 config.SCHEMA 驱动（Schema 驱动，可扩展）。
- 表头可点击排序（Quasar sortable）；文本列关键字筛选 + 枚举列下拉多选。
- 行点击下钻查看原文 Markdown 与元数据。
- 扫描在协程内进行并刷新进度，避免长时间无响应。
"""
import asyncio
import csv
import io
import os
import time
import traceback
from typing import Dict, List

from nicegui import ui

from . import config, scanner, extractor, store
from . import keywords as kw_mod
from . import keywords_discovery as discovery
from . import graph_view
from . import quality_scorer
from . import sync
from .config import FieldType
from .logger import log

# 全局状态
records: List[Dict] = []          # 当前全部记录（含 _path/_raw）
filter_widgets: Dict[str, object] = {}  # 字段 key -> 筛选控件
table = None                      # 表格引用
path_input = None
status_label = None
stats_label = None
cross_stats_label = None         # 交叉统计（语言×类型）
# 新版统计面板：4 指标卡 + 3 行 chips
metric_files = None        # 扫描的 MD 文件数
metric_total = None         # 抽取出的记录数
metric_matched = None       # 关键词已匹配记录数
metric_unmatched = None     # 关键词未匹配记录数
metric_platforms = None
metric_quality = None      # 平均质量分（P2-2）
chips_types = None
chips_langs = None
chips_platforms = None
chips_unmatched = None  # P2：待识别独立行（语言="通用" 的记录）
global_search_input = None        # P1-1：全文检索输入框
filter_container = None
detail_dialog = None
meta_md = None
body_md = None
_scanning: bool = False           # 重入保护：扫描中禁止再次触发
_candidate_updating: bool = False  # 重入保护：chip 回调中禁止 clear 容器
scan_btn = None                   # 扫描按钮引用（用于禁用/启用）
candidate_container = None        # 候选关键词面板容器（动态重建）
candidate_actions = None           # 候选操作按钮行（全加载/热加载/重置）
# P1-2：LLM 抽取 UI 控件
_llm_enabled_switch = None
_llm_url_input = None
_llm_key_input = None
_llm_model_input = None
_llm_status_label = None
# P2-5/6：项目筛选 + 时间筛选
project_filter_widget = None       # 项目多选筛选
time_filter_widget = None          # 时间范围筛选
# P2-2：质量评分筛选
quality_filter_widget = None       # 质量等级单选筛选
# P2-3：定时增量同步
_sync_timer = None                 # NiceGUI 定时器句柄（None=未开启）
autosync_switch = None             # 自动同步开关
autosync_interval = None           # 自动同步间隔下拉

# P2-4：详情页代码高亮（highlight.js via CDN；离线时优雅降级为纯文本代码块）
HIGHLIGHT_HEAD_HTML = (
    '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/'
    'highlight.js@11.9.0/styles/{theme}.min.css">'.replace("{theme}", config.CODE_HIGHLIGHT_THEME)
    + '<script src="https://cdn.jsdelivr.net/npm/'
    'highlight.js@11.9.0/lib/highlight.min.js"></script>'
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


def _on_row_click(e) -> None:
    """表格行点击事件：解析行数据并打开详情。"""
    args = e.args or {}
    row = args.get("row") or (args.get("args") or {}).get("row")
    if row:
        _open_detail(row)


def _open_detail(row: Dict) -> None:
    """打开详情对话框，展示元数据与原文 Markdown。"""
    q_score = row.get(config.QUALITY_SCORE_KEY)
    q_tier = quality_scorer.tier_of(q_score)
    meta_md.set_content(
        f"**来源**：{row.get('source', '')}  \n"
        f"**路径**：`{row.get('_path', '')}`  \n"
        f"**语言范畴**：{row.get('language', '')}  \n"
        f"**平台**：{row.get('platform', '')}  \n"
        f"**类型**：{row.get('type', '')}  \n"
        f"**严重度**：{row.get('severity', '')}  \n"
        f"**质量分**：{q_score if q_score is not None else '未评分'}（{q_tier}）  \n"
        f"**标签**：{row.get('tags', '')}"
    )
    body_md.set_content(row.get("_raw", "") or "（无内容）")
    # P2-4：内容渲染后对其内代码块做语法高亮（highlight.js 全局已加载）
    if config.CODE_HIGHLIGHT_ENABLED:
        ui.run_javascript(
            "setTimeout(function(){if(window.hljs){"
            "var bs=document.querySelectorAll('#detail-body pre code');"
            "for(var i=0;i<bs.length;i++){try{hljs.highlightElement(bs[i]);}catch(e){}}}"
            "},80);}"
        )
    detail_dialog.open()


def _apply_filters() -> None:
    """根据全局搜索 + 列筛选控件过滤记录并刷新表格与统计。"""
    if table is None:
        return
    # P1-1：全局搜索关键词（跨全部字段 + 原文正文）
    global_term = (global_search_input.value or "").strip().lower() if global_search_input else ""
    visible = []
    for r in records:
        ok = True
        # 全局搜索优先（AND 语义：先过全局再过列筛选）
        if global_term:
            # 拼接所有可见字段 + 原文用于全文匹配
            searchable_parts = [
                _flatten(r.get(f.key, "")) for f in config.SCHEMA
            ] + [r.get("_raw", "")]
            searchable = " ".join(searchable_parts).lower()
            if global_term not in searchable:
                continue  # 不匹配全文检索，跳过此记录
        # 列筛选器
        for f in config.SCHEMA:
            if not f.filterable:
                continue
            w = filter_widgets.get(f.key)
            if w is None:
                continue
            val = w.value
            if f.ftype == FieldType.TEXT:
                if val:
                    if val.lower() not in str(r.get(f.key, "")).lower():
                        ok = False
                        break
            elif f.ftype == FieldType.SELECT:
                if val and r.get(f.key) != val:
                    ok = False
                    break
            elif f.ftype == FieldType.MULTI:
                if val:
                    cell = r.get(f.key) or []
                    if not any(v in cell for v in val):
                        ok = False
                        break
        # P2-5：项目筛选（按 memory 父目录分组）
        if ok and project_filter_widget is not None:
            proj_val = project_filter_widget.value
            if proj_val:
                rec_project = r.get("source", "").split("/")[0] if r.get("source") else ""
                if rec_project not in proj_val:
                    continue  # 不在选中项目中，跳过
        # P2-6：时间范围筛选
        if ok and time_filter_widget is not None:
            time_val = time_filter_widget.value
            if time_val and time_val != "all":
                days_map = {"7d": 7, "30d": 30, "90d": 90}
                days = days_map.get(time_val, 0)
                if days > 0:
                    mtime_val = r.get("_mtime", 0)
                    if mtime_val:
                        cutoff = time.time() - days * 86400
                        if mtime_val < cutoff:
                            continue  # 超过时间范围，跳过
        # P2-2：质量等级筛选
        if ok and quality_filter_widget is not None:
            q_val = quality_filter_widget.value
            if q_val and q_val != "all":
                rec_tier = quality_scorer.tier_of(r.get(config.QUALITY_SCORE_KEY))
                if rec_tier != q_val:
                    continue  # 等级不匹配，跳过
        if ok:
            visible.append(r)
    _update_stats(visible)
    table.rows = _flatten_records(visible)


def _update_stats(rows: List[Dict]) -> None:
    """更新顶部统计：4 个指标卡 + 3 行分类 chips。"""
    # 1) 统计计数
    type_counts: Dict[str, int] = {}
    lang_counts: Dict[str, int] = {}
    platform_counts: Dict[str, int] = {}
    cross_counts: Dict[str, Dict[str, int]] = {}
    for r in rows:
        t = r.get("type", "其他")
        type_counts[t] = type_counts.get(t, 0) + 1
        for lg in (r.get("language") or []):
            lang_counts[lg] = lang_counts.get(lg, 0) + 1
            cross_counts.setdefault(lg, {}).setdefault(t, 0)
            cross_counts[lg][t] += 1
        for pl in (r.get("platform") or []):
            platform_counts[pl] = platform_counts.get(pl, 0) + 1

    # 2) 顶部 4 个指标卡
    matched = sum(1 for r in rows if r.get("language") != ["通用"])
    unmatched = len(rows) - matched
    metric_total.text = f"{len(rows)}"
    metric_matched.text = f"{matched}"
    metric_unmatched.text = f"{unmatched}"
    metric_platforms.text = f"{len(platform_counts)}"
    # P2-2：平均质量分（仅统计已评分整数）
    _scores = [r.get(config.QUALITY_SCORE_KEY) for r in rows
               if isinstance(r.get(config.QUALITY_SCORE_KEY), int)]
    metric_quality.text = f"{sum(_scores) / len(_scores):.0f}" if _scores else "-"

    # 3) 三行 chips（Top N）—— 语言行排除"通用"和"通用（待分类）"（独立显示）
    _render_chips(chips_types, type_counts, max_n=8, color_map=TYPE_COLOR)
    matched_langs = {k: v for k, v in lang_counts.items() if k not in ("通用", "通用（待分类）")}
    _render_chips(chips_langs, matched_langs, max_n=8, color_map=LANG_COLOR)
    _render_chips(chips_platforms, platform_counts, max_n=6, color_map=PLATFORM_COLOR)
    # 4) 待识别行（语言="通用" + 待分类统计）
    unmatched_count = lang_counts.get("通用", 0)
    pending_count = lang_counts.get("通用（待分类）", 0)
    if chips_unmatched is not None:
        chips_unmatched.clear()
        if unmatched_count > 0:
            with chips_unmatched:
                ui.chip(f"⚠ 通用 · {unmatched_count}", removable=False, color="orange").props("dense square")
                ui.label("（关键词未覆盖）").classes("text-caption text-grey")
        if pending_count > 0:
            with chips_unmatched:
                ui.chip(f"📋 待分类 · {pending_count}", removable=False, color="blue").props("dense square")
                ui.label(f"（已加载但仍为临时分类）").classes("text-caption text-grey")
        if unmatched_count == 0 and pending_count == 0:
            with chips_unmatched:
                ui.chip("✓ 全部已匹配", removable=False, color="green").props("dense square")

    # 4) 交叉统计：Top3 语言 × 全部类型
    if cross_stats_label is not None and cross_counts:
        top3 = sorted(lang_counts.items(), key=lambda x: -x[1])[:3]
        lines = []
        for lg_name, _ in top3:
            if lg_name in cross_counts:
                items = " · ".join(f"{t}:{c}" for t, c in cross_counts[lg_name].items())
                lines.append(f"**{lg_name}** → {items}")
        cross_stats_label.content = "<br>".join(lines)
    elif cross_stats_label is not None:
        cross_stats_label.content = ""


# 颜色映射（NiceGUI chip 颜色名）
TYPE_COLOR: Dict[str, str] = {
    "问题": "red", "陷阱": "orange", "最佳实践": "green",
    "规范": "teal", "经验": "blue", "发布": "purple",
    "环境配置": "indigo", "命令行": "cyan", "兼容性": "amber",
    "其他": "grey",
}
LANG_COLOR: Dict[str, str] = {
    "Python": "green", "JavaScript/TS": "yellow", "Go": "cyan",
    "Rust": "orange", "Shell/Bash": "blue", "PowerShell": "indigo",
    "Batch/CMD": "purple", "Docker": "teal", "Git/GitHub": "pink",
    "通用": "grey", "其他": "grey",
}
PLATFORM_COLOR: Dict[str, str] = {
    "Windows": "blue", "Linux": "orange", "macOS": "purple",
    "跨平台": "grey",
}


def _render_chips(container, counts: Dict[str, int], max_n: int, color_map: Dict[str, str]) -> None:
    """在给定容器里渲染 chips。"""
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


def _build_filter_bar() -> None:
    """依据 SCHEMA 重建筛选栏控件（每次扫描后重算候选）。

    紧凑布局：标签+控件水平排列，整体 3 行，q-pa-xs 最小内边距。
    """
    global project_filter_widget, time_filter_widget
    filter_widgets.clear()
    filter_container.clear()
    with filter_container:
        with ui.card().classes("w-full q-pa-sm").style("background: #fafbfc"):
            # ---------- 第 1 行：关键字搜索 ----------
            with ui.row().classes("w-full gap-3 items-center"):
                ui.label("🔍").classes("text-body1")
                for f in config.SCHEMA:
                    if not f.filterable or f.ftype != FieldType.TEXT:
                        continue
                    with ui.row().classes("items-center gap-1"):
                        ui.label(f.label).classes("text-caption text-grey").style("min-width:50px")
                        w = ui.input(placeholder="关键字…").props("dense outlined clearable")
                        w.style("min-width: 130px")
                        w.on("update:model-value", lambda *_: _apply_filters())
                        filter_widgets[f.key] = w
            # ---------- 第 2 行：多选 ----------
            with ui.row().classes("w-full gap-3 items-center q-mt-xs"):
                ui.label("🏷️").classes("text-body1")
                for f in config.SCHEMA:
                    if not f.filterable or f.ftype != FieldType.MULTI:
                        continue
                    with ui.row().classes("items-center gap-1"):
                        ui.label(f.label).classes("text-caption text-grey").style("min-width:50px")
                        w = ui.select(options=f.options, multiple=True, clearable=True)
                        w.props("dense outlined use-chips")
                        w.style("min-width: 140px")
                        w.on("update:model-value", lambda *_: _apply_filters())
                        filter_widgets[f.key] = w
            # ---------- 第 3 行：单选 + 项目 + 时间 ----------
            with ui.row().classes("w-full gap-3 items-center q-mt-xs"):
                ui.label("⚙️").classes("text-body1")
                for f in config.SCHEMA:
                    if not f.filterable or f.ftype != FieldType.SELECT:
                        continue
                    with ui.row().classes("items-center gap-1"):
                        ui.label(f.label).classes("text-caption text-grey").style("min-width:50px")
                        # 头部插入"全部"选项（值为 None = 不筛选）
                        opts = {None: "全部"}
                        opts.update({opt: opt for opt in f.options})
                        w = ui.select(options=opts, value=None)
                        w.props("dense outlined")
                        w.style("min-width: 100px")
                        w.on("update:model-value", lambda *_: _apply_filters())
                        filter_widgets[f.key] = w
                # P2-5：项目筛选
                projects = sorted({r.get("source", "").split("/")[0]
                                  for r in records if r.get("source", "")})
                with ui.row().classes("items-center gap-1"):
                    ui.label("项目").classes("text-caption text-grey").style("min-width:50px")
                    if projects:
                        project_filter_widget = ui.select(
                            options=projects, multiple=True, clearable=True
                        )
                        project_filter_widget.props("dense outlined use-chips")
                    else:
                        project_filter_widget = ui.select(
                            options=[], multiple=True, clearable=True
                        )
                        project_filter_widget.props("dense outlined use-chips disable")
                        project_filter_widget.disable()
                    project_filter_widget.style("min-width: 130px")
                    project_filter_widget.on("update:model-value", lambda *_: _apply_filters())
                # P2-6：时间范围
                with ui.row().classes("items-center gap-1"):
                    ui.label("时间").classes("text-caption text-grey").style("min-width:50px")
                    time_filter_widget = ui.select(
                        options={"all": "全部", "7d": "7天", "30d": "30天", "90d": "90天"},
                        value="all",
                    )
                    time_filter_widget.props("dense outlined")
                    time_filter_widget.style("min-width: 80px")
                    time_filter_widget.on("update:model-value", lambda *_: _apply_filters())
                # P2-2：质量等级筛选
                with ui.row().classes("items-center gap-1"):
                    ui.label("质量").classes("text-caption text-grey").style("min-width:50px")
                    quality_filter_widget = ui.select(
                        options={"all": "全部", "高": "高", "中": "中",
                                 "低": "低", "未评分": "未评分"},
                        value="all",
                    )
                    quality_filter_widget.props("dense outlined")
                    quality_filter_widget.style("min-width: 90px")
                    quality_filter_widget.on("update:model-value", lambda *_: _apply_filters())


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


def _flatten(v) -> str:
    """将列表/标量统一为可写入 CSV 的字符串。"""
    if isinstance(v, list):
        return "; ".join(str(x) for x in v)
    return "" if v is None else str(v)


def _export_csv() -> None:
    """导出当前表格可见记录为 CSV（含文件路径）并触发下载。"""
    if not table or not table.rows:
        ui.notify("表格无数据可导出", type="warning")
        return
    fieldnames = [f.key for f in config.SCHEMA] + config.EXTRA_EXPORT_FIELDS
    buf = io.StringIO()
    # 加 BOM 让 Excel 正确识别 UTF-8
    buf.write("\ufeff")
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for r in table.rows:
        row = {f.key: _flatten(r.get(f.key)) for f in config.SCHEMA}
        row["_path"] = r.get("_path", "")
        writer.writerow(row)
    # 转 bytes 传给 ui.download
    content = buf.getvalue().encode("utf-8")
    log.info("CSV导出: 记录数=%d, 字节数=%d", len(table.rows), len(content))
    ui.download(content, "memoalign.csv", "text/csv; charset=utf-8")
    ui.notify(f"已导出 CSV：{len(table.rows)} 条记录", type="positive")


def _export_xlsx() -> None:
    """导出当前表格可见记录为 Excel（需 pip install openpyxl，失败自动回落 CSV）。"""
    try:
        import openpyxl  # noqa: PLC0415
    except ImportError:
        ui.notify("未安装 openpyxl，已改为导出 CSV。可执行 pip install openpyxl 启用 Excel 导出", type="warning")
        _export_csv()
        return

    try:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "MemoAlign"
        # 表头：Schema 字段 + 质量分 + _path
        fieldnames = [f.key for f in config.SCHEMA] + config.EXTRA_EXPORT_FIELDS
        ws.append(fieldnames)
        for r in (table.rows or []):
            row = [_flatten(r.get(f.key)) for f in config.SCHEMA]
            row.append(r.get("_path", ""))
            ws.append(row)
        # 自适应列宽
        for col in ws.columns:
            max_len = max((len(str(cell.value or "")) for cell in col), default=10)
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, 50)
        buf = io.BytesIO()
        wb.save(buf)
        ui.download(buf.getvalue(), "memoalign.xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        ui.notify("已导出 Excel", type="positive")
    except Exception as exc:
        log.error("Excel 导出失败: %s", exc)
        ui.notify(f"Excel 导出失败: {exc}", type="negative")


def _export_md() -> None:
    """按类型分组导出 Markdown 摘要并触发下载。"""
    rows = table.rows or []
    if not rows:
        ui.notify("表格无数据可导出", type="warning")
        return
    groups: Dict[str, List[Dict]] = {}
    for r in rows:
        groups.setdefault(r.get("type", "其他"), []).append(r)
    lines = ["# MemoAlign 导出摘要", f"\n共 {len(rows)} 条记录，按类型分组：\n"]
    for typ, items in groups.items():
        lines.append(f"## {typ}（{len(items)}）")
        for r in items:
            lang = _flatten(r.get("language"))
            av = _flatten(r.get("avoidance"))
            q = r.get(config.QUALITY_SCORE_KEY)
            q_text = f" 质量分:{q}" if isinstance(q, int) else ""
            lines.append(f"- **{r.get('content', '')}** 〔{lang}〕 {av}{q_text}")
        lines.append("")
    # 转 bytes 给 ui.download
    content = "\n".join(lines).encode("utf-8")
    log.info("MD导出: 记录数=%d, 字节数=%d", len(rows), len(content))
    ui.download(content, "memoalign.md", "text/markdown; charset=utf-8")
    ui.notify(f"已导出 Markdown：{len(rows)} 条记录", type="positive")


def _reset_filters() -> None:
    """清空所有筛选控件（含全局搜索）并刷新。"""
    if global_search_input is not None:
        global_search_input.value = ""
    if project_filter_widget is not None:
        project_filter_widget.value = []
    if time_filter_widget is not None:
        time_filter_widget.value = "all"
    for f in config.SCHEMA:
        w = filter_widgets.get(f.key)
        if w is None:
            continue
        w.value = [] if f.ftype == FieldType.MULTI else None
    _apply_filters()


def _open_dir_browser() -> None:
    """打开目录浏览器对话框：树形展示 + 上下级导航 + 选中回填。"""
    # 状态：当前浏览的目录（不依赖全局变量）
    state = {"current": path_input.value or config.DEFAULT_ROOT}
    if not os.path.isdir(state["current"]):
        # 兜底：取父目录，若仍不存在则用 C:\
        parent = os.path.dirname(state["current"])
        state["current"] = parent if parent and os.path.isdir(parent) else "C:\\"

    with ui.dialog() as dialog, ui.card().style("min-width: 700px; max-height: 85vh"):
        ui.label("📁 浏览目录").classes("text-h6 q-mb-sm")
        # 路径显示
        nav_label = ui.label().classes("text-body1 text-weight-medium q-mb-sm")
        # 父目录按钮 + 当前路径
        nav_row = ui.row().classes("items-center gap-2 w-full q-mb-sm")
        folder_list = ui.column().classes("w-full").style(
            "max-height: 50vh; overflow-y: auto; border: 1px solid #e0e0e0; border-radius: 4px; padding: 4px;"
        )

        def refresh():
            """刷新当前目录的子目录列表。"""
            nav_label.text = f"📂 {state['current']}"
            nav_row.clear()
            folder_list.clear()
            with nav_row:
                # 父目录快捷按钮
                parent = os.path.dirname(state["current"])
                if parent and parent != state["current"]:
                    def go_up():
                        state["current"] = parent
                        refresh()
                    ui.button("⬆ 上级目录", on_click=go_up).props("outline dense")
                # 常用盘符快捷
                for drive in ["C:\\", "D:\\", "E:\\"]:
                    if os.path.isdir(drive) and drive != state["current"]:
                        ui.button(drive, on_click=lambda _, d=drive: (state.update({"current": d}), refresh())).props("outline dense size=sm")
            with folder_list:
                try:
                    entries = sorted(
                        [e for e in os.scandir(state["current"])
                         if e.is_dir() and not e.name.startswith(".")],
                        key=lambda e: e.name.lower()
                    )
                except PermissionError:
                    ui.label("⚠️ 无权限访问此目录").classes("text-negative")
                    return
                except OSError as e:
                    ui.label(f"⚠️ 读取失败: {e}").classes("text-negative")
                    return
                if not entries:
                    ui.label("（无子目录）").classes("text-grey q-pa-md")
                for entry in entries[:200]:  # 限制最多 200 个
                    def go_in(p=entry.path):
                        state["current"] = p
                        refresh()
                    with ui.row().classes(
                        "w-full items-center cursor-pointer hover:bg-blue-50 q-pa-xs"
                    ).style("border-radius: 4px;").on("click", go_in):
                        ui.icon("folder", color="amber")
                        ui.label(entry.name).classes("text-body2")

        refresh()
        # 底部按钮
        with ui.row().classes("w-full justify-end q-mt-md gap-2"):
            ui.button("取消", on_click=dialog.close).props("flat")
            def select():
                path_input.value = state["current"]
                dialog.close()
                ui.notify(f"已选择: {state['current']}", type="positive")
            ui.button("✅ 选择此目录", on_click=select, color="primary")
    dialog.open()


def _open_graph() -> None:
    """打开图谱视图对话框：treemap / 条形图 两种可切换。"""
    if not records:
        ui.notify("请先扫描以获取数据", type="warning")
        return
    try:
        with ui.dialog(value=True) as graph_dialog:
            graph_dialog.props("maximized")
            with ui.card().classes("w-full").style("height:92vh"):
                # ---------- 顶部：标题 + 切换 + 关闭 ----------
                with ui.row().classes("items-center gap-2 q-mb-sm"):
                    ui.label("数据图谱").classes("text-h6")
                    mode_switch = ui.toggle(
                        options={"treemap": "层级图", "bar": "条形图"},
                        value="treemap",
                    ).props("dense")
                    ui.button("关闭", on_click=graph_dialog.close).props("flat")
                # ---------- 图表区域（独立，不在 row 内） ----------
                echart_container = ui.element("div").style("width:100%;height:78vh")

                def refresh_graph():
                    mode = mode_switch.value or "treemap"
                    opt = graph_view.build_graph_option(records, mode=mode)
                    echart_container.clear()
                    with echart_container:
                        ui.echart(opt).style("width:100%;height:75vh")

                mode_switch.on("update:model-value", lambda *_: refresh_graph())
                # 初始渲染
                with echart_container:
                    ui.echart(graph_view.build_graph_option(records)).style("width:100%;height:75vh")
    except Exception as exc:
        log.error("图谱渲染失败: %s", exc)
        ui.notify(f"图谱渲染失败: {exc}", type="negative")


async def _hot_reload_keywords() -> None:
    """热加载关键词：清空缓存 + 重新抽取，让统计数字立即反映新关键词。"""
    try:
        kw_mod.reload()
        log.info("用户触发关键词热加载")
        from . import store as store_mod
        store_mod.reset()
        if records:  # 已有数据 → 自动重扫
            ui.notify("关键词已热加载，正在重新抽取…", type="info")
            await run_scan()
        else:
            ui.notify("关键词已热加载，请点「扫描」", type="info")
    except Exception as exc:
        ui.notify(f"热加载失败：{exc}", type="negative")
        log.error("热加载失败: %s", exc)


async def _reset_keywords_default() -> None:
    """一键恢复 keywords_data.json 到 git 版本并热加载 + 自动重扫。"""
    import subprocess
    from pathlib import Path
    repo = Path(__file__).parent.parent
    try:
        result = subprocess.run(
            ["git", "checkout", "--", "src/keywords_data.json"],
            cwd=str(repo), capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            ui.notify(f"恢复失败: {result.stderr.strip()}", type="negative")
            return
        kw_mod.reload()
        log.info("用户触发关键词恢复为默认")
        from . import store as store_mod
        store_mod.reset()
        if records:
            ui.notify("关键词已恢复，正在重新抽取…", type="info")
            await run_scan()
        else:
            ui.notify("关键词已恢复为默认", type="positive")
    except FileNotFoundError:
        ui.notify("未找到 Git，请确认已安装", type="negative")
    except Exception as exc:
        ui.notify(f"恢复异常: {exc}", type="negative")
        log.error("恢复关键词失败: %s", exc)


def _refresh_candidates() -> None:
    """刷新候选关键词面板：操作按钮在独立行（不被 clear 影响）。"""
    global _candidate_updating
    if candidate_container is None or candidate_actions is None:
        return
    # 防止 chip 回调内部 clear 导致"parent element deleted"
    if _candidate_updating:
        return
    candidates = discovery.get_candidates()
    candidate_actions.clear()
    candidate_actions.style("display:flex")
    # 操作按钮行（独立，不会被候选面板 clear 删除）
    with candidate_actions:
        ui.button("全加载", on_click=_add_all_candidates, icon="download").props("dense outline color=orange")
        ui.button("清空待分类", on_click=_clear_pending_keywords).props("dense outline")
        ui.button("热加载", on_click=_hot_reload_keywords).props("dense")
        ui.button("重置", on_click=_reset_keywords_default).props("dense outline")
        if not candidates:
            ui.icon("check_circle", color="green", size="sm")
            ui.label("✅ 全部关键词已匹配").classes("text-body2 text-positive")
    # 候选面板：只放 chips
    candidate_container.style("display:block")
    candidate_container.clear()
    if candidates:
        with candidate_container:
            with ui.row().classes("items-center gap-2"):
                ui.icon("lightbulb", color="orange", size="sm")
                ui.label(f"候选关键词（{len(candidates)} 个）— 点击加入词库").classes("text-body2 text-weight-medium")
            with ui.row().classes("w-full gap-1 flex-wrap q-mt-xs"):
                for word, freq in candidates[:30]:
                    label = f"{word}({freq})"
                    chip = ui.chip(label, removable=True, color="orange")
                    chip.props("dense square clickable")
                    chip.on("remove", lambda w=word: _add_candidate_keyword(w))
                    chip.on("click", lambda w=word: _add_candidate_keyword(w))
    log.info("候选面板已刷新: %d关键词", len(candidates))


async def _add_candidate_keyword(word: str) -> None:
    """将候选关键词加入默认分类并热加载 + 重扫。"""
    global _candidate_updating
    _candidate_updating = True
    try:
        ok = kw_mod.add_keyword("language_keywords", "通用（待分类）", word)
        if ok:
            kw_mod.reload()
            from . import store as store_mod
            store_mod.reset()
            await run_scan()
            ui.notify(f"已添加关键词并重扫: {word}", type="positive")
        else:
            ui.notify(f"关键词已存在: {word}", type="warning")
    except Exception as exc:
        ui.notify(f"添加失败: {exc}", type="negative")
        log.error("添加候选关键词失败: %s", exc)
    finally:
        _candidate_updating = False
        _refresh_candidates()  # 安全更新面板（chip 回调已结束）


async def _add_all_candidates() -> None:
    """一键加载所有候选词：先清旧批、再写入新批、自动重扫。"""
    global _candidate_updating
    candidates = discovery.get_candidates()
    if not candidates:
        ui.notify("没有候选关键词", type="warning")
        return
    _candidate_updating = True
    try:
        kw_mod.clear_category("language_keywords", "通用（待分类）")
        added = 0
        for word, _ in candidates:
            if kw_mod.add_keyword("language_keywords", "通用（待分类）", word):
                added += 1
        kw_mod.reload()
        from . import store as store_mod
        store_mod.reset()
        await run_scan()
        ui.notify(f"已加载 {added} 个关键词，已匹配↑ 待识别↓", type="positive")
        log.info("全加载候选关键词: %d个", added)
    except Exception as exc:
        ui.notify(f"加载失败: {exc}", type="negative")
        log.error("全加载候选关键词失败: %s", exc)
    finally:
        _candidate_updating = False
        _refresh_candidates()


async def _clear_pending_keywords() -> None:
    """一键清空"通用（待分类）"分类下的所有关键词，并重扫。"""
    try:
        removed = kw_mod.clear_category("language_keywords", "通用（待分类）")
        # 立即清空候选缓存与面板，给用户即时反馈
        discovery.reset_candidates()
        _refresh_candidates()
        from . import store as store_mod
        store_mod.reset()
        await run_scan()
        ui.notify(f"已清空'待分类'，移除 {removed} 个关键词并重扫", type="positive")
        log.info("清空待分类关键词: 移除%d个", removed)
    except Exception as exc:
        ui.notify(f"清空失败: {exc}", type="negative")
        log.error("清空待分类失败: %s", exc)



def _update_llm_config() -> None:
    """从 UI 控件同步 LLM 配置到 config 模块（P1-2）。"""
    if _llm_url_input is not None:
        config.LLM_BASE_URL = _llm_url_input.value.strip() or config.LLM_BASE_URL
    if _llm_key_input is not None:
        config.LLM_API_KEY = _llm_key_input.value.strip() or config.LLM_API_KEY
    if _llm_model_input is not None:
        config.LLM_MODEL = _llm_model_input.value.strip() or config.LLM_MODEL
    if _llm_enabled_switch is not None:
        config.LLM_ENABLED = _llm_enabled_switch.value
    # 更新状态提示
    if _llm_status_label is not None:
        if config.LLM_ENABLED and config.LLM_API_KEY:
            _llm_status_label.text = f"已启用 → {config.LLM_MODEL}"
            _llm_status_label.classes("text-caption text-positive")
        elif config.LLM_ENABLED:
            _llm_status_label.text = "已启用但未配置密钥"
            _llm_status_label.classes("text-caption text-warning")
        else:
            _llm_status_label.text = "未启用"
            _llm_status_label.classes("text-caption text-grey")


async def _batch_llm_re_extract() -> None:
    """批量 LLM 重抽：用 LLM 对所有记录重新抽取（P1-2）。

    先同步 LLM 配置，再逐条重抽（缓存无效直接覆盖），带进度提示。
    """
    global _scanning
    if _scanning:
        ui.notify("操作正在进行中，请等待完成", type="warning")
        return
    _scanning = True
    if scan_btn is not None:
        scan_btn.disable()

    try:
        _update_llm_config()
        if not config.LLM_API_KEY:
            ui.notify("请先输入有效的 API Key", type="negative")
            return
        if not records:
            ui.notify("请先扫描以获取记录", type="warning")
            return

        total = len(records)
        ui.notify(f"开始 LLM 重抽，共 {total} 篇…", type="info")
        status_label.text = f"LLM 重抽中… 0/{total}"
        log.info("开始 LLM 批量重抽: 记录数=%d", total)

        cache = store.load_cache()
        for i, r in enumerate(records):
            meta_path = r.get("_path", "")
            if not meta_path or not os.path.isfile(meta_path):
                continue
            try:
                # 构造 FileMeta 以调用 extractor（force_llm=True 跳过规则抽取）
                from .scanner import FileMeta
                meta = FileMeta(
                    path=meta_path,
                    name=os.path.splitext(os.path.basename(meta_path))[0],
                    project=os.path.basename(os.path.dirname(os.path.dirname(meta_path))),
                    mtime=os.path.getmtime(meta_path),
                    size=os.path.getsize(meta_path),
                )
                new_records = extractor.extract(meta, force_llm=True)
                if not new_records:
                    continue
                store.put_all(cache, meta, new_records)
                # LLM 模式：只替换第 1 条；其余保持原样
                new_records[0]["id"] = r.get("id", i + 1)
                records[i] = new_records[0]
            except Exception as exc:
                log.warning("LLM 重抽异常（跳过该条）: %s\n%s", meta_path, traceback.format_exc())
            if (i + 1) % 3 == 0:
                status_label.text = f"LLM 重抽中… {i + 1}/{total}"
                await asyncio.sleep(0.1)

        store.save_cache(cache)
        _build_filter_bar()
        _update_stats(records)
        table.rows = _flatten_records(records)
        status_label.text = f"LLM 重抽完成 · 共 {len(records)} 篇"
        ui.notify(f"LLM 重抽完成，共 {len(records)} 篇", type="positive")
        log.info("LLM 批量重抽结束: 成功=%d", len(records))
    except Exception as exc:
        log.error("LLM 批量重抽异常: %s\n%s", exc, traceback.format_exc())
        ui.notify(f"LLM 重抽失败: {exc}", type="negative")
    finally:
        _scanning = False
        if scan_btn is not None:
            scan_btn.enable()


async def _batch_quality_score() -> None:
    """批量质量评分：对当前所有记录打分（P2-2）。

    启用 LLM 且配置密钥时走 LLM 语义打分，否则使用离线启发式（始终可用）；
    评分写回记录与缓存，便于持久化与刷新。
    """
    global _scanning
    if _scanning:
        ui.notify("操作正在进行中，请等待完成", type="warning")
        return
    _scanning = True
    if scan_btn is not None:
        scan_btn.disable()

    try:
        _update_llm_config()
        if not records:
            ui.notify("请先扫描以获取记录", type="warning")
            return

        use_llm = bool(config.LLM_ENABLED) and bool(config.LLM_API_KEY)
        if not use_llm:
            ui.notify("未启用 LLM，将使用离线启发式评分", type="info")
        total = len(records)
        status_label.text = f"质量评分中… 0/{total}"
        log.info("开始批量质量评分: 记录数=%d, 模式=%s", total, "LLM" if use_llm else "heuristic")

        # 1) 就地打分
        quality_scorer.score_records(records, llm=use_llm)

        # 2) 按路径分组写回缓存（保留 _raw_preview 供详情展示）
        from collections import defaultdict
        cache = store.load_cache()
        by_path: dict = defaultdict(list)
        for r in records:
            by_path[r.get("_path", "")].append(r)
        for path, recs in by_path.items():
            if not path or not os.path.isfile(path):
                continue
            try:
                for r in recs:
                    # 缓存写入前补全 _raw（来自预览），使详情展示不丢失
                    if not r.get("_raw"):
                        r["_raw"] = r.get("_raw_preview", "")
                from .scanner import FileMeta
                meta = FileMeta(
                    path=path,
                    name=os.path.splitext(os.path.basename(path))[0],
                    project=os.path.basename(os.path.dirname(os.path.dirname(path))),
                    mtime=os.path.getmtime(path),
                    size=os.path.getsize(path),
                )
                store.put_all(cache, meta, recs)
            except Exception as exc:
                log.warning("质量分写回缓存异常（跳过该文件）: %s\n%s", path, traceback.format_exc())

        store.save_cache(cache)
        _build_filter_bar()
        _update_stats(records)
        table.rows = _flatten_records(records)
        status_label.text = f"质量评分完成 · 共 {len(records)} 篇"
        ui.notify(f"质量评分完成：{len(records)} 篇（{'LLM' if use_llm else '启发式'}）", type="positive")
        log.info("批量质量评分结束: 成功=%d", len(records))
    except Exception as exc:
        log.error("批量质量评分异常: %s\n%s", exc, traceback.format_exc())
        ui.notify(f"质量评分失败: {exc}", type="negative")
    finally:
        _scanning = False
        if scan_btn is not None:
            scan_btn.enable()


async def _incremental_sync() -> None:
    """增量同步：对当前根目录重扫，对比前后差异并通知（P2-3）。

    复用 run_scan 的增量缓存机制；仅额外计算差异摘要推送给用户。
    """
    global _scanning
    if _scanning:
        return  # 静默跳过，避免定时器与手动扫描竞态
    # 快照旧记录（按 _path）
    old_snapshot = [dict(r) for r in records]
    await run_scan()
    diff = sync.compute_diff(old_snapshot, records)
    summary = sync.summarize(diff)
    if diff["added"] or diff["changed"] or diff["removed"]:
        ui.notify(f"增量同步：{summary}", type="info")
        log.info("增量同步完成: %s", summary)
    else:
        ui.notify("增量同步：无变化", type="positive")


def _toggle_autosync() -> None:
    """自动同步开关：开启则启动 NiceGUI 定时器，关闭则取消。"""
    global _sync_timer
    try:
        if autosync_switch is not None and autosync_switch.value:
            interval = config.AUTOSYNC_INTERVALS.get(
                autosync_interval.value if autosync_interval else config.AUTOSYNC_DEFAULT_INTERVAL,
                config.AUTOSYNC_INTERVALS[config.AUTOSYNC_DEFAULT_INTERVAL],
            )
            if _sync_timer is not None:
                _sync_timer.cancel()
            # ui.timer 接受协程回调；周期性触发增量同步
            _sync_timer = ui.timer(interval, _incremental_sync)
            ui.notify(f"已启用自动同步（每 {interval // 60} 分钟）", type="positive")
            log.info("自动同步已启用: 间隔=%d秒", interval)
        else:
            if _sync_timer is not None:
                _sync_timer.cancel()
                _sync_timer = None
            ui.notify("已关闭自动同步", type="warning")
            log.info("自动同步已关闭")
    except Exception as exc:
        log.error("切换自动同步异常: %s", exc)
        ui.notify(f"自动同步切换失败: {exc}", type="negative")


async def run_scan() -> None:
    """扫描 → 抽取（增量缓存）→ 渲染表格与筛选栏。

    内置重入保护：_scanning 为 True 时拒绝重复触发，防止协程竞态。
    """
    global _scanning, table
    # 重入保护（P0-6）—— 防止并发扫描导致 records/cache 数据竞态
    if _scanning:
        ui.notify("扫描正在进行中，请等待完成", type="warning")
        return
    _scanning = True
    if scan_btn is not None:
        scan_btn.disable()

    try:
        root = (path_input.value or "").strip() or config.DEFAULT_ROOT
        if not os.path.isdir(root):
            ui.notify(f"目录不存在：{root}", type="negative")
            status_label.text = "就绪 · 目录不存在"
            _scanning = False
            if scan_btn is not None:
                scan_btn.enable()
            return

        ui.notify("开始扫描…", type="info")
        status_label.text = "扫描中…"
        table.rows = []
        records.clear()
        discovery.reset_candidates()
        # 强制清空文件缓存，确保抽取逻辑变更后不会读到旧缓存（导致候选发现不执行）
        store.reset()
        await asyncio.sleep(0.1)

        cache = store.load_cache()
        metas = scanner.scan_memory_md(root)
        total = len(metas)
        # 更新"文件"指标（仅在首次/重置扫描时设置，不被筛选过滤）
        if metric_files is not None:
            metric_files.text = f"{total}"
        log.info("开始扫描: root=%s, 文件数=%d", root, total)

        for i, meta in enumerate(metas, 1):
            try:
                need = store.needs_update(meta, cache)
                if need:
                    file_records = extractor.extract(meta)
                else:
                    file_records = store.get_cached_records(meta, cache)
                # P2-2：扫描即做离线启发式质量评分（保证质量分列始终有数据）
                quality_scorer.score_records(file_records)
                if need:
                    store.put_all(cache, meta, file_records)
                for j, rec in enumerate(file_records):
                    rec["id"] = i + j
                    rec["_mtime"] = meta.mtime
                    records.append(rec)
            except Exception as exc:
                log.error("处理文件异常，已跳过: %s\n%s", meta.path, traceback.format_exc())
                placeholder = {f.key: (["通用"] if f.ftype == FieldType.MULTI else
                                       (f.options[0] if f.options else ""))
                               for f in config.SCHEMA}
                placeholder.update({"content": "解析失败", "source": f"{meta.project}/{meta.name}",
                                    "_path": meta.path, "_raw": "", "id": i, "_mtime": meta.mtime})
                records.append(placeholder)
            if i % 5 == 0:
                status_label.text = f"扫描中 {i}/{total}"
                await asyncio.sleep(0.1)

        store.save_cache(cache)
        _build_filter_bar()
        _update_stats(records)
        _refresh_candidates()
        table.rows = _flatten_records(records)
        status_label.text = f"就绪 · 共 {len(records)} 篇"
        ui.notify(f"扫描完成，共 {len(records)} 篇", type="positive")
        log.info("扫描结束: 记录数=%d", len(records))
    finally:
        _scanning = False
        if scan_btn is not None:
            scan_btn.enable()


@ui.page("/")
def create_ui() -> None:
    """构建页面布局（@ui.page 装饰器注册为根路由 "/"，由 NiceGUI 按需调用）。"""
    global path_input, status_label, stats_label, filter_container, table
    global detail_dialog, meta_md, body_md, scan_btn
    global candidate_container, candidate_actions, cross_stats_label, global_search_input
    global metric_files, metric_total, metric_matched, metric_unmatched, metric_platforms, metric_quality
    global chips_types, chips_langs, chips_platforms, chips_unmatched
    global _llm_enabled_switch, _llm_url_input, _llm_key_input, _llm_model_input, _llm_status_label
    global _sync_timer, autosync_switch, autosync_interval

    # P2-4：注入 highlight.js（详情代码块语法高亮；离线时优雅降级）
    if config.CODE_HIGHLIGHT_ENABLED:
        ui.add_head_html(HIGHLIGHT_HEAD_HTML)

    # 标题栏
    with ui.card().classes("w-full q-pa-md"):
        ui.label("MemoAlign · 记忆对齐分析器").classes("text-h5 text-weight-bold")
        ui.label("将 **/memory/*.md 笔记对齐为结构化表格：排序 / 筛选 / 下钻 / 导出").classes("text-subtitle2 text-grey")

    # 路径输入 + 操作按钮
    with ui.card().classes("w-full q-pa-md"):
        with ui.row().classes("items-end gap-2 w-full"):
            path_input = ui.input("扫描根目录", value=config.DEFAULT_ROOT).props(
                "outlined clearable").classes("grow")
            ui.button("📁 浏览", on_click=_open_dir_browser).props("outline")
            scan_btn = ui.button("扫描", on_click=run_scan)
            ui.button("图谱视图", on_click=_open_graph)
            ui.button("重置筛选", on_click=_reset_filters)
            ui.button("导出 CSV", on_click=_export_csv)
            ui.button("导出 Excel", on_click=_export_xlsx)
            ui.button("导出 MD", on_click=_export_md)
        status_label = ui.label("就绪").classes("text-caption text-grey")

        # P1-1：全文检索输入框
        with ui.row().classes("items-end gap-2 w-full q-mt-sm"):
            global_search_input = ui.input(
                "全文检索", placeholder="搜索全部字段及原文内容…"
            ).props("outlined clearable dense").classes("grow")
            global_search_input.on("update:model-value", lambda *_: _apply_filters())

        # P2-3：定时增量同步
        with ui.row().classes("items-center gap-2 w-full q-mt-sm"):
            ui.button("增量同步", on_click=_incremental_sync).props("outline")
            autosync_switch = ui.switch("自动同步", value=config.AUTOSYNC_ENABLED).props("dense")
            autosync_switch.on("update:model-value", lambda *_: _toggle_autosync())
            autosync_interval = ui.select(
                options={k: f"{int(v) // 60}分" for k, v in config.AUTOSYNC_INTERVALS.items()},
                value=config.AUTOSYNC_DEFAULT_INTERVAL,
            ).props("dense outlined").style("min-width:90px")
            autosync_interval.on("update:model-value", lambda *_: _toggle_autosync())

        # P1-2：LLM 抽取设置（可折叠）
        with ui.expansion("LLM 抽取设置", icon="smart_toy", value=False).classes("w-full q-mt-sm"):
            with ui.row().classes("items-end gap-3 w-full"):
                _llm_enabled_switch = ui.switch("启用 LLM", value=config.LLM_ENABLED).props("dense")
                _llm_enabled_switch.on("update:model-value", lambda *_: _update_llm_config())
                _llm_status_label = ui.label(
                    "已启用" if config.LLM_ENABLED and config.LLM_API_KEY else "未启用"
                ).classes("text-caption text-grey")
            with ui.row().classes("items-end gap-2 w-full q-mt-sm"):
                _llm_url_input = ui.input("API 地址", value=config.LLM_BASE_URL).props(
                    "outlined dense").classes("grow")
                _llm_model_input = ui.input("模型", value=config.LLM_MODEL).props(
                    "outlined dense").style("max-width:160px")
            with ui.row().classes("items-end gap-2 w-full q-mt-sm"):
                _llm_key_input = ui.input(
                    "API Key", value=os.environ.get("MEMOALIGN_LLM_API_KEY", ""),
                    password=True, password_toggle_button=True,
                ).props("outlined dense").classes("grow")
                ui.button("批量 LLM 重抽", on_click=_batch_llm_re_extract).props("outline")
                ui.button("批量质量评分", on_click=_batch_quality_score).props("outline")

    # 统计面板：4 指标 + 3 行 chips（紧凑布局）
    with ui.card().classes("w-full q-pa-sm").style("background: #fafbfc"):
        with ui.row().classes("w-full gap-4 items-center"):
            for icon, label, ref_name, color in [
                ("folder", "文件", "metric_files", "blue"),
                ("article", "总数", "metric_total", "primary"),
                ("check_circle", "已匹配", "metric_matched", "green"),
                ("warning", "待识别", "metric_unmatched", "orange"),
                ("devices", "平台", "metric_platforms", "primary"),
                ("score", "质量均分", "metric_quality", "teal"),
            ]:
                with ui.row().classes("items-center gap-2").style("min-width: 100px"):
                    ui.icon(icon, color=color, size="sm")
                    with ui.column().classes("gap-0"):
                        ui.label(label).classes("text-caption text-grey").style("line-height:1; margin:0")
                        val_label = ui.label("0").classes("text-h6 text-weight-bold").style("line-height:1.1")
                        if ref_name == "metric_files":
                            metric_files = val_label
                        elif ref_name == "metric_total":
                            metric_total = val_label
                        elif ref_name == "metric_matched":
                            metric_matched = val_label
                        elif ref_name == "metric_unmatched":
                            metric_unmatched = val_label
                        else:
                            metric_platforms = val_label
            # 右侧 chips 区域（占满剩余空间）
            with ui.column().classes("col gap-0"):
                with ui.row().classes("items-center gap-1"):
                    ui.label("类型").classes("text-caption text-grey").style("min-width:32px")
                    chips_types = ui.row().classes("gap-1")
                with ui.row().classes("items-center gap-1"):
                    ui.label("语言").classes("text-caption text-grey").style("min-width:32px")
                    chips_langs = ui.row().classes("gap-1")
                with ui.row().classes("items-center gap-1"):
                    ui.label("平台").classes("text-caption text-grey").style("min-width:32px")
                    chips_platforms = ui.row().classes("gap-1")
                # 待识别行（语言="通用" 的记录，关键词未覆盖）
                with ui.row().classes("items-center gap-1"):
                    ui.label("待识别").classes("text-caption text-grey").style("min-width:32px")
                    chips_unmatched = ui.row().classes("gap-1")
        # 交叉统计（语言 × 类型）— 单独一行
        cross_stats_label = ui.markdown("").classes("text-caption q-mt-xs")

    # 候选操作行（全加载/热加载/重置 — 独立于面板，不会被 clear 删除）
    candidate_actions = ui.row().classes("w-full q-px-sm q-py-xs items-center gap-2").style("display:none")
    # 候选关键词面板（扫描后显示，有候选→chips，无候选→绿色完成提示）
    candidate_container = ui.card().classes("w-full q-pa-sm").style("display:none; background:#fff8e1")
    # 筛选栏容器
    filter_container = ui.element("div").classes("w-full")

    # 表格容器：sticky header + 表格内置滚动，保证表头与列严格对齐
    with ui.card().classes("w-full q-pa-none"):
        table = ui.table(
            columns=_build_columns(),
            rows=[],
            row_key="id",
            pagination={"rowsPerPage": 50, "page": 1, "rowsPerPageOptions": [20, 50, 100, 0]},
        ).props(
            "flat bordered separator=cell dense wrap-cells "
            "sticky-header "
            "table-style='max-height:62vh'"
        ).classes("w-full")
        table.on("rowClick", _on_row_click)
        # P2-2：质量分列自定义渲染（彩色等级徽标，未评分显示灰字）
        table.add_slot("body-cell-quality_score", """
          <q-td :props="props">
            <template v-if="props.value == null || props.value === ''">
              <span class="text-grey">未评分</span>
            </template>
            <template v-else>
              <q-badge
                :color="props.value >= 80 ? 'green' : (props.value >= 60 ? 'orange' : 'red')">
                {{ props.value }} {{ props.value >= 80 ? '高' : (props.value >= 60 ? '中' : '低') }}
              </q-badge>
            </template>
          </q-td>
        """)

    # 详情对话框（一次构建，复用）
    detail_dialog = ui.dialog()
    with detail_dialog:
        with ui.card().classes("w-full max-w-3xl"):
            ui.label("笔记详情").classes("text-h6")
            meta_md = ui.markdown()
            # P2-4：包一层带 id 的容器，便于 JS 精准定位代码块做高亮
            with ui.column().props("id=detail-body").classes("w-full"):
                body_md = ui.markdown()
            ui.button("关闭", on_click=detail_dialog.close).props("flat")
