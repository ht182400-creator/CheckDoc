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

# 检索防抖秒数：停止输入后延迟检索。配合 IME 合成标志，规避拼音输入法合成
# 中间态（如「向dao」）误搜——上屏成中文并停顿后才会触发检索，最终命中一定正确（P1-1 补丁）。
SEARCH_DEBOUNCE_SEC = 0.25

# 客户端注入的 JS：在 capture 阶段监听原生 compositionstart/end，把合成状态写入
# window.__memoalign_composing。NiceGUI 的 QInput 不会把 compositionstart/end/input
# 作为 Python 回调转发（实测），故必须在客户端用原生 DOM 事件桥接回 Python 端。
# 参考 Vue3 社区 IME 标准做法（composition 期间 isComposing=True 跳过搜索）。
IME_COMPOSITION_JS = """
(function(){
  if (window.__memoalign_ime_bound) return;
  window.__memoalign_ime_bound = true;
  window.__memoalign_composing = false;
  function isInput(t){
    if (!t) return false;
    if (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA') return true;
    if (t.matches && t.matches('.q-field__native')) return true;
    return false;
  }
  document.addEventListener('compositionstart', function(e){
    if (isInput(e.target)) window.__memoalign_composing = true;
  }, true);
  document.addEventListener('compositionend', function(e){
    if (isInput(e.target)) window.__memoalign_composing = false;
  }, true);
})();
"""

# JS 是否已注入（避免重复注入）。注入失败则降级为纯防抖（仍正确，仅偶尔中间误搜）。
_IME_JS_INJECTED = False


def _inject_ime_composition_js() -> None:
    """向已连接的客户端注入原生 composition 监听（idempotent）。

    通过 NiceGUI 的 ui.run_javascript 在浏览器端执行 IME_COMPOSITION_JS，把 IME 合成
    状态桥接为 window.__memoalign_composing，供 Python 端防抖到点时读取。
    注入失败（如极端环境 run_javascript 不可用）仅 WARNING 并降级为纯防抖，不影响主流程。
    """
    global _IME_JS_INJECTED
    if _IME_JS_INJECTED:
        return
    try:
        ui.run_javascript(IME_COMPOSITION_JS)
        _IME_JS_INJECTED = True
        log.debug("IME 合成检测 JS 已注入(客户端桥接就绪)")
    except Exception as exc:
        log.warning("注入 IME 检测 JS 失败(降级纯防抖): %s", exc)


async def _is_composing() -> bool:
    """读取客户端 IME 合成状态（异步，桥接 window.__memoalign_composing）。

    Vue3 标准做法：合成中为 True（如「向dao」态），应推迟搜索；提交中文后为 False。
    读取失败（JS 未注入/客户端断开）返回 False，退化为纯防抖，功能仍正确。
    """
    if not _IME_JS_INJECTED:
        _inject_ime_composition_js()
    try:
        return bool(await ui.run_javascript("return window.__memoalign_composing === true;"))
    except Exception as exc:
        log.debug("读取 IME 合成状态失败(降级为False): %s", exc)
        return False


def _attach_ime_safe_input(widget, on_commit) -> None:
    """为文本输入框绑定「IME 合成安全」的检索回调（P1-1 补丁，参考 Vue3 主流做法）。

    调研结论（Vue3 IME 主流方案 + NiceGUI 源码确认）：
    - 主流：IME 合成期间（compositionstart→compositionend）跳过搜索，提交中文后才搜。
    - 实测确认：NiceGUI 的 Quasar QInput **不把** `compositionstart`/`compositionend`/
      `input` 作为 Python 回调转发（日志证明：绑 input 后搜索整段失效、绑 composition
      后标志恒 False）。故纯 Python 端永远拿不到合成状态。
    - **正确桥接**：在客户端用原生 DOM 事件监听 composition（capture 阶段），把状态写
      入 `window.__memoalign_composing`，Python 端防抖到点时 `await ui.run_javascript`
      读取该标志——合成中推迟、提交后才搜。这是 NiceGUI 下唯一可靠路径。

    主触发：`update:model-value`（NiceGUI 已验证可靠触发每一键，含合成中的拼音态）。
    双保险：防抖 SEARCH_DEBOUNCE_SEC——即便 JS 注入失败/合成标志取不到，停输后才检索，
    IME 上屏成中文并停顿后必用中文检索，最终命中一定正确。

    覆盖场景：英文/数字/标识符（无合成，停输后防抖检索）、中文经输入法（合成中推迟、
    提交后检索）、中英文混输、粘贴、清除（空词显示全部）。
    注意：仅 SELECT/时间等选择型控件不绑定此逻辑（它们无 IME 问题）。
    """
    # 计时器句柄（闭包内持有，便于重置/取消）
    timer_ref = [None]

    async def _fire():
        """防抖到点：取消计时器后，若仍在 IME 合成则推迟，否则执行检索。"""
        if timer_ref[0] is not None:
            timer_ref[0].cancel()
            timer_ref[0] = None
        if await _is_composing():
            log.debug("IME 合成中(JS 标志=True)，推迟搜索，等待提交中文")
            _schedule()
            return
        on_commit()

    def _schedule():
        """每次输入重置计时器，仅停止输入 SEARCH_DEBOUNCE_SEC 后才检索。"""
        if timer_ref[0] is not None:
            timer_ref[0].cancel()
        timer_ref[0] = ui.timer(SEARCH_DEBOUNCE_SEC, _fire)

    def _on_model_value(*_):
        """主触发：update:model-value（每键触发，已验证能到达 Python 端）。"""
        _schedule()

    # 主触发：update:model-value（每键触发；合成态的拼音由 _fire 的 JS 标志拦截）
    widget.on("update:model-value", _on_model_value)
    # 客户端连接后注入 IME 合成监听（0.5s 足够本地连接），idempotent。
    try:
        ui.timer(0.5, _inject_ime_composition_js, once=True)
    except Exception as exc:
        log.warning("调度 IME JS 注入定时器失败(降级纯防抖): %s", exc)


def _compute_visible() -> List[Dict]:
    """按当前筛选控件计算「可见完整记录」（含 _raw，供详情/导出按需取数）。

    与 _apply_filters 解耦：筛选是用户低频触发，导出/详情需完整字段（不截断、
    含原文），故返回服务端完整记录而非瘦身后端表格行。
    """
    if not S.records:
        log.debug("_compute_visible: S.records 为空，返回 []")
        return []
    # P1-1：全局搜索关键词（跨全部字段 + 原文正文）
    raw_term = S.global_search_input.value if S.global_search_input else None
    global_term = H._normalize_search_text(raw_term)
    log.debug("_compute_visible 开始: records=%d, 全局检索原始值=%r, 归一化后=%r",
              len(S.records), raw_term, global_term)
    visible = []
    # 调试用：全局检索无命中时采样前几条记录的 searchable 片段
    _dbg_samples = []
    for r in S.records:
        ok = True
        # 全局搜索优先（AND 语义：先过全局再过列筛选）
        if global_term:
            # 原文正文：优先用完整 _raw；缓存记录已被 store.put_all 剔除 _raw，
            # 回落到 _raw_preview（前 RAW_PREVIEW_LEN 字），否则正文永远搜不到（P1-1 补丁）。
            raw_body = r.get("_raw") or r.get("_raw_preview", "")
            searchable_parts = [
                H._flatten(r.get(f.key, "")) for f in config.SCHEMA
            ] + [raw_body]
            searchable = H._normalize_search_text(" ".join(searchable_parts))
            if global_term not in searchable:
                # 采样最多 3 条未命中记录，记录其 content 与 searchable 前 120 字
                if len(_dbg_samples) < 3:
                    _dbg_samples.append(
                        "content=%r has_raw=%s has_preview=%s searchable_len=%d searchable[:120]=%r" % (
                            H._flatten(r.get("content"))[:40],
                            bool(r.get("_raw")),
                            bool(r.get("_raw_preview")),
                            len(searchable),
                            searchable[:120],
                        )
                    )
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
                    norm_val = H._normalize_search_text(val)
                    norm_cell = H._normalize_search_text(str(r.get(f.key, "")))
                    if norm_val not in norm_cell:
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
    # 汇总：命中数（DEBUG 写文件，避免每次按键刷屏控制台）
    log.debug("_compute_visible 结束: 命中=%d/%d, 全局检索归一化=%r",
              len(visible), len(S.records), global_term)
    # 有检索词但 0 命中时，采样升 WARNING 便于定位（低频、值得关注）
    if global_term and not visible and _dbg_samples:
        for i, s in enumerate(_dbg_samples):
            log.warning("全文检索 0 命中采样[%d]: %s", i, s)
    return visible


def _apply_filters() -> None:
    """根据全局搜索 + 列筛选控件过滤记录并刷新表格与统计（显示行已瘦身）。"""
    if S.table is None:
        return
    visible = _compute_visible()
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
                        _attach_ime_safe_input(w, _apply_filters)
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
