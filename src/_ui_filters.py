# encoding: utf-8
"""UI 筛选与统计层：筛选器控件构建、过滤逻辑、统计面板更新。

依赖：共享状态（_ui_state）、纯函数辅助（_ui_helpers）、配置（config）。
"""
from typing import Dict, List

from nicegui import ui

from . import config, quality_scorer
from . import _ui_state as S
from . import _ui_helpers as H
from .config import FieldType
from .logger import log


def _apply_filters() -> None:
    """根据全局搜索 + 列筛选控件过滤记录并刷新表格与统计。"""
    if S.table is None:
        return
    # P1-1：全局搜索关键词（跨全部字段 + 原文正文）
    global_term = (S.global_search_input.value or "").strip().lower() if S.global_search_input else ""
    visible = []
    for r in S.records:
        ok = True
        # 全局搜索优先（AND 语义：先过全局再过列筛选）
        if global_term:
            searchable_parts = [
                H._flatten(r.get(f.key, "")) for f in config.SCHEMA
            ] + [r.get("_raw", "")]
            searchable = " ".join(searchable_parts).lower()
            if global_term not in searchable:
                continue  # 不匹配全文检索，跳过此记录
        # 列筛选器
        for f in config.SCHEMA:
            if not f.filterable:
                continue
            w = S.filter_widgets.get(f.key)
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
        if ok and S.project_filter_widget is not None:
            proj_val = S.project_filter_widget.value
            if proj_val:
                rec_project = r.get("source", "").split("/")[0] if r.get("source") else ""
                if rec_project not in proj_val:
                    continue  # 不在选中项目中，跳过
        # P2-6：时间范围筛选
        if ok and S.time_filter_widget is not None:
            time_val = S.time_filter_widget.value
            if time_val and time_val != "all":
                days = config.TIME_FILTER_DAYS.get(time_val, 0)
                if not H.record_within_time_range(r, days):
                    continue  # 超过时间范围，跳过
        # P2-2：质量等级筛选
        if ok and S.quality_filter_widget is not None:
            q_val = S.quality_filter_widget.value
            if q_val and q_val != "all":
                rec_tier = quality_scorer.tier_of(r.get(config.QUALITY_SCORE_KEY))
                if rec_tier != q_val:
                    continue  # 等级不匹配，跳过
        if ok:
            visible.append(r)
    _update_stats(visible)
    S.table.rows = H._flatten_records(visible)


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
    matched = sum(1 for r in rows if r.get("language") != [config.LANG_GENERIC])
    unmatched = len(rows) - matched
    S.metric_total.text = f"{len(rows)}"
    S.metric_matched.text = f"{matched}"
    S.metric_unmatched.text = f"{unmatched}"
    S.metric_platforms.text = f"{len(platform_counts)}"
    # P2-2：平均质量分（仅统计已评分整数）
    _scores = [r.get(config.QUALITY_SCORE_KEY) for r in rows
               if isinstance(r.get(config.QUALITY_SCORE_KEY), int)]
    S.metric_quality.text = f"{sum(_scores) / len(_scores):.0f}" if _scores else "-"

    # 3) 三行 chips（Top N）—— 语言行排除"通用"和"通用（待分类）"（独立显示）
    H._render_chips(S.chips_types, type_counts, max_n=8, color_map=config.TYPE_COLOR_MAP)
    matched_langs = {k: v for k, v in lang_counts.items()
                     if k not in (config.LANG_GENERIC, config.LANG_PENDING)}
    H._render_chips(S.chips_langs, matched_langs, max_n=8, color_map=config.LANG_COLOR_MAP)
    H._render_chips(S.chips_platforms, platform_counts, max_n=6, color_map=config.PLATFORM_COLOR_MAP)
    # 4) 待识别行（语言="通用" + 待分类统计）
    unmatched_count = lang_counts.get(config.LANG_GENERIC, 0)
    pending_count = lang_counts.get(config.LANG_PENDING, 0)
    if S.chips_unmatched is not None:
        S.chips_unmatched.clear()
        if unmatched_count > 0:
            with S.chips_unmatched:
                ui.chip(f"⚠ 通用 · {unmatched_count}", removable=False, color="orange").props("dense square")
                ui.label("（关键词未覆盖）").classes("text-caption text-grey")
        if pending_count > 0:
            with S.chips_unmatched:
                ui.chip(f"📋 待分类 · {pending_count}", removable=False, color="blue").props("dense square")
                ui.label("（已加载但仍为临时分类）").classes("text-caption text-grey")
        if unmatched_count == 0 and pending_count == 0:
            with S.chips_unmatched:
                ui.chip("✓ 全部已匹配", removable=False, color="green").props("dense square")

    # 5) 交叉统计：Top3 语言 × 全部类型
    if S.cross_stats_label is not None and cross_counts:
        top3 = sorted(lang_counts.items(), key=lambda x: -x[1])[:3]
        lines = []
        for lg_name, _ in top3:
            if lg_name in cross_counts:
                items = " · ".join(f"{t}:{c}" for t, c in cross_counts[lg_name].items())
                lines.append(f"**{lg_name}** → {items}")
        S.cross_stats_label.content = "<br>".join(lines)
    elif S.cross_stats_label is not None:
        S.cross_stats_label.content = ""


def _build_filter_bar() -> None:
    """依据 SCHEMA 重建筛选栏控件（每次扫描后重算候选）。

    紧凑布局：标签+控件水平排列，整体 3 行，q-pa-xs 最小内边距。
    """
    S.filter_widgets.clear()
    S.filter_container.clear()
    with S.filter_container:
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
                        S.filter_widgets[f.key] = w
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
                        S.filter_widgets[f.key] = w
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
                        S.filter_widgets[f.key] = w
                # P2-5：项目筛选
                projects = sorted({r.get("source", "").split("/")[0]
                                   for r in S.records if r.get("source", "")})
                with ui.row().classes("items-center gap-1"):
                    ui.label("项目").classes("text-caption text-grey").style("min-width:50px")
                    if projects:
                        S.project_filter_widget = ui.select(
                            options=projects, multiple=True, clearable=True
                        )
                        S.project_filter_widget.props("dense outlined use-chips")
                    else:
                        S.project_filter_widget = ui.select(
                            options=[], multiple=True, clearable=True
                        )
                        S.project_filter_widget.props("dense outlined use-chips disable")
                        S.project_filter_widget.disable()
                    S.project_filter_widget.style("min-width: 130px")
                    S.project_filter_widget.on("update:model-value", lambda *_: _apply_filters())
                # P2-6：时间范围
                with ui.row().classes("items-center gap-1"):
                    ui.label("时间").classes("text-caption text-grey").style("min-width:50px")
                    S.time_filter_widget = ui.select(
                        options={"all": "全部", "7d": "7天", "30d": "30天", "90d": "90天"},
                        value="all",
                    )
                    S.time_filter_widget.props("dense outlined")
                    S.time_filter_widget.style("min-width: 80px")
                    S.time_filter_widget.on("update:model-value", lambda *_: _apply_filters())
                # P2-2：质量等级筛选
                with ui.row().classes("items-center gap-1"):
                    ui.label("质量").classes("text-caption text-grey").style("min-width:50px")
                    S.quality_filter_widget = ui.select(
                        options={"all": "全部", "高": "高", "中": "中",
                                 "低": "低", "未评分": "未评分"},
                        value="all",
                    )
                    S.quality_filter_widget.props("dense outlined")
                    S.quality_filter_widget.style("min-width: 90px")
                    S.quality_filter_widget.on("update:model-value", lambda *_: _apply_filters())


def _reset_filters() -> None:
    """清空所有筛选控件（含全局搜索）并刷新。"""
    if S.global_search_input is not None:
        S.global_search_input.value = ""
    if S.project_filter_widget is not None:
        S.project_filter_widget.value = []
    if S.time_filter_widget is not None:
        S.time_filter_widget.value = "all"
    for f in config.SCHEMA:
        w = S.filter_widgets.get(f.key)
        if w is None:
            continue
        w.value = [] if f.ftype == FieldType.MULTI else None
    _apply_filters()
