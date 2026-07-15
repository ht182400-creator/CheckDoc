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
global_search_input = None        # P1-1：全文检索输入框
filter_container = None
detail_dialog = None
meta_md = None
body_md = None
_scanning: bool = False           # 重入保护：扫描中禁止再次触发
scan_btn = None                   # 扫描按钮引用（用于禁用/启用）
candidate_container = None        # 候选关键词面板容器
candidate_label = None            # 候选关键词列表标签（Markdown）
# P1-2：LLM 抽取 UI 控件
_llm_enabled_switch = None
_llm_url_input = None
_llm_key_input = None
_llm_model_input = None
_llm_status_label = None
# P2-5/6：项目筛选 + 时间筛选
project_filter_widget = None       # 项目多选筛选
time_filter_widget = None          # 时间范围筛选


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
            # 文本列省略，避免撑破布局；完整内容见详情
            col["style"] = (col.get("style", "") +
                            "max-width:360px;overflow:hidden;text-overflow:ellipsis;"
                            "white-space:nowrap;")
        cols.append(col)
    return cols


def _on_row_click(e) -> None:
    """表格行点击事件：解析行数据并打开详情。"""
    args = e.args or {}
    row = args.get("row") or (args.get("args") or {}).get("row")
    if row:
        _open_detail(row)


def _open_detail(row: Dict) -> None:
    """打开详情对话框，展示元数据与原文 Markdown。"""
    meta_md.set_content(
        f"**来源**：{row.get('source', '')}  \n"
        f"**路径**：`{row.get('_path', '')}`  \n"
        f"**语言范畴**：{row.get('language', '')}  \n"
        f"**平台**：{row.get('platform', '')}  \n"
        f"**类型**：{row.get('type', '')}  \n"
        f"**严重度**：{row.get('severity', '')}  \n"
        f"**标签**：{row.get('tags', '')}"
    )
    body_md.set_content(row.get("_raw", "") or "（无内容）")
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
        if ok:
            visible.append(r)
    table.rows = visible
    _update_stats(visible)


def _update_stats(rows: List[Dict]) -> None:
    """更新顶部统计（总数 + 按类型/语言/平台分布 + 交叉统计）。"""
    type_counts: Dict[str, int] = {}
    lang_counts: Dict[str, int] = {}
    platform_counts: Dict[str, int] = {}
    cross_counts: Dict[str, Dict[str, int]] = {}  # 语言 × 类型 交叉矩阵
    for r in rows:
        t = r.get("type", "其他")
        type_counts[t] = type_counts.get(t, 0) + 1
        for lg in (r.get("language") or []):
            lang_counts[lg] = lang_counts.get(lg, 0) + 1
            # 交叉统计：语言 → 类型
            cross_counts.setdefault(lg, {}).setdefault(t, 0)
            cross_counts[lg][t] += 1
        for pl in (r.get("platform") or []):
            platform_counts[pl] = platform_counts.get(pl, 0) + 1
    type_str = "  ".join(f"{k}:{v}" for k, v in type_counts.items())
    lang_str = "  ".join(f"{k}:{v}" for k, v in lang_counts.items())
    plat_str = "  ".join(f"{k}:{v}" for k, v in platform_counts.items())
    stats_label.text = (
        f"共 {len(rows)} 篇  |  类型 → {type_str}  |  语言 → {lang_str}  |  平台 → {plat_str}"
    )
    # 交叉统计：展示 Top 语言×Top 类型（取覆盖最多的前几项）
    top_lang = sorted(lang_counts.items(), key=lambda x: -x[1])[:6]
    if top_lang and cross_stats_label is not None:
        lines = ["**语言×类型 交叉**："]
        for lg_name, _ in top_lang:
            if lg_name in cross_counts:
                items = " ".join(f"{t}:{c}" for t, c in cross_counts[lg_name].items())
                lines.append(f"  {lg_name} → {items}")
        cross_stats_label.text = "  |  ".join(lines)


def _build_filter_bar() -> None:
    """依据 SCHEMA 重建筛选栏控件（每次扫描后重算候选）。"""
    global project_filter_widget, time_filter_widget
    filter_widgets.clear()
    filter_container.clear()
    with filter_container:
        with ui.row().classes("flex-wrap gap-2 items-end"):
            for f in config.SCHEMA:
                if not f.filterable:
                    continue
                if f.ftype == FieldType.SELECT:
                    w = ui.select(options=f.options, label=f.label, clearable=True)
                    w.props("dense outlined")
                elif f.ftype == FieldType.MULTI:
                    w = ui.select(options=f.options, label=f.label, multiple=True)
                    w.props("dense outlined multiple use-chips")
                else:
                    w = ui.input(label=f"搜索 {f.label}", placeholder="关键字…")
                    w.props("dense outlined clearable")
                w.on("update:model-value", lambda *_: _apply_filters())
                filter_widgets[f.key] = w
            # P2-5：项目筛选（按 memory 父目录分组，多选）
            projects = sorted({r.get("source", "").split("/")[0]
                              for r in records if r.get("source", "")})
            if projects:
                project_filter_widget = ui.select(
                    options=projects, label="项目", multiple=True, clearable=True
                )
                project_filter_widget.props("dense outlined multiple use-chips")
                project_filter_widget.on("update:model-value", lambda *_: _apply_filters())
            # P2-6：时间范围筛选
            time_filter_widget = ui.select(
                options={"all": "全部时间", "7d": "最近 7 天", "30d": "最近 30 天", "90d": "最近 90 天"},
                label="时间范围", value="all",
            )
            time_filter_widget.props("dense outlined")
            time_filter_widget.on("update:model-value", lambda *_: _apply_filters())


def _flatten(v) -> str:
    """将列表/标量统一为可写入 CSV 的字符串。"""
    if isinstance(v, list):
        return "; ".join(str(x) for x in v)
    return "" if v is None else str(v)


def _export_csv() -> None:
    """导出当前表格可见记录为 CSV（含文件路径）并触发下载。"""
    buf = io.StringIO()
    # Schema 字段 + _path（便于用户定位原文）
    fieldnames = [f.key for f in config.SCHEMA] + ["_path"]
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for r in (table.rows or []):
        row = {f.key: _flatten(r.get(f.key)) for f in config.SCHEMA}
        row["_path"] = r.get("_path", "")
        writer.writerow(row)
    ui.download(buf.getvalue(), "memoalign.csv", "text/csv")
    ui.notify("已导出 CSV", type="positive")


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
        # 表头：Schema 字段 + _path
        fieldnames = [f.key for f in config.SCHEMA] + ["_path"]
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
    groups: Dict[str, List[Dict]] = {}
    for r in rows:
        groups.setdefault(r.get("type", "其他"), []).append(r)
    lines = ["# MemoAlign 导出摘要", ""]
    for typ, items in groups.items():
        lines.append(f"## {typ}（{len(items)}）")
        for r in items:
            lang = _flatten(r.get("language"))
            av = _flatten(r.get("avoidance"))
            lines.append(f"- **{r.get('content', '')}** 〔{lang}〕 {av}")
        lines.append("")
    ui.download("\n".join(lines), "memoalign.md", "text/markdown")
    ui.notify("已导出 Markdown", type="positive")


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


def _open_graph() -> None:
    """打开图谱视图对话框（P2-1：ECharts 力导向聚类图）。"""
    if not records:
        ui.notify("请先扫描以获取数据", type="warning")
        return
    try:
        option = graph_view.build_graph_option(records)
        with ui.dialog(value=True) as graph_dialog:
            graph_dialog.props("maximized")
            with ui.card().classes("w-full h-full"):
                ui.label("知识图谱").classes("text-h6")
                ui.echart(option).classes("w-full").style("height:75vh")
                ui.button("关闭", on_click=graph_dialog.close).props("flat")
    except Exception as exc:
        log.error("图谱渲染失败: %s", exc)
        ui.notify(f"图谱渲染失败: {exc}", type="negative")


def _hot_reload_keywords() -> None:
    """热加载关键词：从 JSON 重新读取，更新内存中 config 模块的全局变量。

    无需重启 NiceGUI 服务，下次抽取自动使用新关键词。
    """
    try:
        kw_mod.reload()
        ui.notify("关键词已从文件热加载，下次抽取生效", type="positive")
        log.info("用户触发关键词热加载")
    except Exception as exc:
        ui.notify(f"热加载失败：{exc}", type="negative")
        log.error("热加载失败: %s", exc)


def _refresh_candidates() -> None:
    """刷新候选关键词面板：从 discovery 缓存读取并渲染。"""
    if candidate_label is None or candidate_container is None:
        return
    candidates = discovery.get_candidates()
    if not candidates:
        candidate_container.style("display:none")
        return
    candidate_container.style("display:block")
    # 构建候选列表 Markdown（词 + 频次 + 添加按钮？Markdown 不支持按钮，
    # 先用文本展示，后续可升级为可交互列表）
    lines = [f"### 🔍 候选关键词（共 {len(candidates)} 个）",
             "> 以下技术术语在扫描中未被现有词库覆盖，可编辑 `src/keywords_data.json` 手动添加。",
             ""]
    for word, freq in candidates[:20]:  # 展示 top 20
        lines.append(f"- `{word}`（出现 {freq} 次）")
    candidate_label.set_content("\n".join(lines))


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
                rec = extractor.extract(meta, force_llm=True)
                store.put(cache, meta, rec)
                rec["id"] = r.get("id", i + 1)
                records[i] = rec
            except Exception as exc:
                log.warning("LLM 重抽异常（跳过该条）: %s\n%s", meta_path, traceback.format_exc())
            if (i + 1) % 3 == 0:
                status_label.text = f"LLM 重抽中… {i + 1}/{total}"
                await asyncio.sleep(0)

        store.save_cache(cache)
        _build_filter_bar()
        table.rows = records
        _update_stats(records)
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
            return

        status_label.text = "扫描中…"
        table.rows = []
        records.clear()
        discovery.reset_candidates()  # 每次扫描前清空旧候选词

        cache = store.load_cache()
        metas = scanner.scan_memory_md(root)
        total = len(metas)
        log.info("开始扫描: root=%s, 文件数=%d", root, total)

        for i, meta in enumerate(metas, 1):
            try:
                if store.needs_update(meta, cache):
                    rec = extractor.extract(meta)
                    store.put(cache, meta, rec)
                else:
                    rec = {k: v for k, v in cache[meta.path].items() if k != "__mtime"}
                    # 缓存命中：将 _raw_preview 映射回 _raw（缓存瘦身后原文为预览截断）
                    raw_val = rec.pop("_raw_preview", "") if "_raw_preview" in rec else rec.get("_raw", "")
                    rec["_raw"] = raw_val
                rec["id"] = i
                rec["_mtime"] = meta.mtime  # P2-6：时间范围筛选需要 mtime
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
                await asyncio.sleep(0)

        store.save_cache(cache)
        _build_filter_bar()
        table.rows = records
        _update_stats(records)
        _refresh_candidates()  # 展示候选关键词
        status_label.text = f"就绪 · 共 {len(records)} 篇"
        ui.notify(f"扫描完成，共 {len(records)} 篇", type="positive")
        log.info("扫描结束: 记录数=%d", len(records))
    finally:
        _scanning = False
        if scan_btn is not None:
            scan_btn.enable()


def create_ui() -> None:
    """构建页面布局（在 ui.run 之前调用一次）。"""
    global path_input, status_label, stats_label, filter_container, table
    global detail_dialog, meta_md, body_md, scan_btn
    global candidate_container, candidate_label, cross_stats_label, global_search_input
    global _llm_enabled_switch, _llm_url_input, _llm_key_input, _llm_model_input, _llm_status_label

    # 标题栏
    with ui.card().classes("w-full q-pa-md"):
        ui.label("MemoAlign · 记忆对齐分析器").classes("text-h5 text-weight-bold")
        ui.label("将 **/memory/*.md 笔记对齐为结构化表格：排序 / 筛选 / 下钻 / 导出").classes("text-subtitle2 text-grey")

    # 路径输入 + 操作按钮
    with ui.card().classes("w-full q-pa-md"):
        with ui.row().classes("items-end gap-2 w-full"):
            path_input = ui.input("扫描根目录", value=config.DEFAULT_ROOT).props(
                "outlined clearable").classes("grow")
            scan_btn = ui.button("扫描", on_click=run_scan)
            ui.button("热加载关键词", on_click=_hot_reload_keywords)
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

    # 统计栏
    with ui.card().classes("w-full q-pa-sm"):
        stats_label = ui.label("共 0 篇").classes("text-body2")
        cross_stats_label = ui.label("").classes("text-caption text-grey")

    # 候选关键词面板（初始隐藏，扫描后如有候选则显示）
    candidate_container = ui.card().classes("w-full q-pa-md").style("display:none")
    with candidate_container:
        ui.label("候选关键词词库").classes("text-subtitle1 text-weight-bold")
        ui.label("扫描时发现未被现有词库覆盖的技术术语，可编辑 src/keywords_data.json 手动添加").classes("text-caption text-grey")
        candidate_label = ui.markdown()

    # 筛选栏容器
    filter_container = ui.element("div").classes("w-full")

    # 表格容器（可滚动）
    with ui.card().classes("w-full q-pa-none").style("max-height:62vh;overflow:auto"):
        table = ui.table(
            columns=_build_columns(),
            rows=[],
            row_key="id",
            pagination={"rowsPerPage": 0, "page": 1},
        ).props("flat bordered separator=cell dense wrap-cells").classes("w-full")
        table.on("rowClick", _on_row_click)

    # 详情对话框（一次构建，复用）
    detail_dialog = ui.dialog()
    with detail_dialog:
        with ui.card().classes("w-full max-w-3xl"):
            ui.label("笔记详情").classes("text-h6")
            meta_md = ui.markdown()
            body_md = ui.markdown()
            ui.button("关闭", on_click=detail_dialog.close).props("flat")
