# encoding: utf-8
"""UI 对话框层：笔记详情、记录编辑、目录浏览、图谱视图。

依赖：共享状态（_ui_state）、纯函数辅助（_ui_helpers）、筛选层（_ui_filters）。
"""
from typing import Dict, List

import os
import traceback
from pathlib import Path
from nicegui import ui

from . import config, scanner, store, record_edit, quality_scorer
from . import _ui_state as S
from . import _ui_helpers as H
from . import _ui_filters as F
from .config import FieldType
from .logger import log


def _open_detail(rec_id) -> None:
    """打开详情对话框：按 id 从服务端完整记录取数（不依赖前端回传的 _raw）。

    表格显示行已瘦身（剔除 _raw、TEXT 截断），故详情不能再用 row["_raw"]；
    改为按 id 在服务端 S.records 查完整记录，按需渲染原文（类比资源管理器
    双击才打开文件读内容），单条推送远小于 1MB，不触发 connection lost。
    """
    rec = H._find_record_by_id(rec_id)
    if rec is None:
        ui.notify("未找到原记录", type="negative")
        return
    S.current_detail_row = rec  # B1：缓存当前记录，供详情内"编辑"按钮引用
    q_score = rec.get(config.QUALITY_SCORE_KEY)
    q_tier = quality_scorer.tier_of(q_score)
    S.meta_md.set_content(
        f"**来源**：{rec.get('source', '')}  \n"
        f"**路径**：`{rec.get('_path', '')}`  \n"
        f"**语言范畴**：{rec.get('language', '')}  \n"
        f"**平台**：{rec.get('platform', '')}  \n"
        f"**类型**：{rec.get('type', '')}  \n"
        f"**严重度**：{rec.get('severity', '')}  \n"
        f"**质量分**：{q_score if q_score is not None else '未评分'}（{q_tier}）  \n"
        f"**标签**：{rec.get('tags', '')}"
    )
    # 详情原文：优先取内存完整 _raw；缓存记录可能只有 _raw_preview，则按 _path
    # 现读源文件兜底（保证详情始终可见完整内容）。
    raw = rec.get("_raw") or ""
    if not raw and rec.get("_path"):
        try:
            raw = Path(rec["_path"]).read_text(encoding="utf-8", errors="replace")
        except OSError:
            raw = rec.get("_raw_preview", "") or "（无内容）"
    S.body_md.set_content(raw or "（无内容）")
    # P2-4：内容渲染后对其内代码块做语法高亮（highlight.js 全局已加载）
    if config.CODE_HIGHLIGHT_ENABLED:
        ui.run_javascript(
            "setTimeout(function(){if(window.hljs){"
            "var bs=document.querySelectorAll('#detail-body pre code');"
            "for(var i=0;i<bs.length;i++){try{hljs.highlightElement(bs[i]);}catch(e){}}}"
            "},80);}"
        )
    S.detail_dialog.open()


def _persist_record_group(rec: Dict) -> None:
    """将某 _path 下的全部记录写回缓存（编辑后持久化）。

    W2：FileMeta 构造下沉到 scanner.FileMeta.from_path，避免 UI 层重复推导 project。
    """
    path = rec.get("_path", "")
    if not path or not os.path.isfile(path):
        return
    group = [r for r in S.records if r.get("_path") == path]
    try:
        cache = store.load_cache()
        meta = scanner.FileMeta.from_path(path)
        store.put_all(cache, meta, group)
        store.save_cache(cache)
    except Exception as exc:
        log.warning("编辑写回缓存失败（不影响内存）: %s\n%s", path, traceback.format_exc())


def _save_record_edit(rec: Dict, widgets: Dict) -> None:
    """将编辑控件的值写回记录，重算质量分，持久化并刷新表格。"""
    try:
        edited = {k: w.value for k, w in widgets.items()}
        record_edit.merge_edit(rec, edited, config.SCHEMA)
        # 编辑后重算质量分（启发式，不触发 LLM）
        rec[config.QUALITY_SCORE_KEY] = quality_scorer.score_record(rec, llm=False)
        _persist_record_group(rec)
        F._build_filter_bar()
        F._update_stats(S.records)
        S.table.rows = H._flatten_records(S.records)
        ui.notify("已保存修改，质量分已重算", type="positive")
        log.info("记录已编辑保存: path=%s", rec.get("_path"))
    except Exception as exc:
        log.error("保存记录编辑失败: %s\n%s", exc, traceback.format_exc())
        ui.notify(f"保存失败: {exc}", type="negative")


def _open_edit(row: Dict, queue: List[Dict] = None) -> None:
    """打开编辑对话框：按 Schema 生成可编辑控件，保存写回并刷新。"""
    rec = H._find_record_by_id(row.get("id"))
    if rec is None:
        ui.notify("未找到原记录", type="negative")
        return
    edit_widgets: Dict[str, object] = {}

    with ui.dialog() as dlg, ui.card().style("min-width:560px; max-height:88vh"):
        ui.label("✏️ 编辑记录").classes("text-h6")
        with ui.scroll_area().style("max-height:62vh"):
            for f in config.SCHEMA:
                cur = rec.get(f.key)
                if f.ftype == FieldType.TEXT:
                    w = ui.textarea(label=f.label, value=cur or "").props("outlined dense")
                elif f.ftype == FieldType.SELECT:
                    opts = {None: "（空）"}
                    opts.update({o: o for o in f.options})
                    w = ui.select(label=f.label, options=opts, value=cur or None).props("dense outlined")
                else:  # MULTI
                    w = ui.select(label=f.label, options=f.options, value=cur or [],
                                  multiple=True).props("dense outlined use-chips")
                edit_widgets[f.key] = w
        q_cur = rec.get(config.QUALITY_SCORE_KEY)
        ui.label(f"当前质量分：{q_cur if isinstance(q_cur, int) else '未评分'}（保存后自动重算）").classes(
            "text-caption text-grey")
        with ui.row().classes("w-full justify-end gap-2 q-mt-sm"):
            ui.button("取消", on_click=dlg.close).props("flat")

            def _save(_=None, d=dlg):
                _save_record_edit(rec, edit_widgets)
                d.close()

            ui.button("保存", on_click=_save, color="primary")

            if queue:
                def _save_next(_=None, d=dlg):
                    _save_record_edit(rec, edit_widgets)
                    d.close()
                    _advance_edit_queue(queue)

                ui.button("保存并下一条", on_click=_save_next, color="primary").props("outline")

    dlg.open()


def _advance_edit_queue(queue: List[Dict]) -> None:
    """编辑队列推进：打开下一条低分记录（队列为空则提示完成）。"""
    if not queue:
        ui.notify("低分修正完成", type="positive")
        return
    nxt = queue.pop(0)
    _open_edit(nxt, queue)


def _correct_low_scores() -> None:
    """从当前可见表格行中收集低分/未评分记录，依次打开编辑。"""
    if not S.records:
        ui.notify("请先扫描", type="warning")
        return
    visible_ids = {r.get("id") for r in (S.table.rows or [])}
    queue = [r for r in S.records if r.get("id") in visible_ids and record_edit.is_low_score(r)]
    if not queue:
        ui.notify("当前无低分记录可修正", type="positive")
        return
    ui.notify(f"共 {len(queue)} 条低分待修正", type="info")
    _open_edit(queue[0], queue[1:])


def _open_dir_browser() -> None:
    """打开目录浏览器对话框：树形展示 + 上下级导航 + 选中回填。"""
    # 状态：当前浏览的目录（不依赖全局变量）
    state = {"current": S.path_input.value or config.DEFAULT_ROOT}
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
                for entry in entries[:config.DIR_BROWSE_MAX]:  # W3：单页上限收敛为常量
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
                S.path_input.value = state["current"]
                dialog.close()
                ui.notify(f"已选择: {state['current']}", type="positive")
            ui.button("✅ 选择此目录", on_click=select, color="primary")
    dialog.open()


def _open_graph() -> None:
    """打开图谱视图对话框：treemap / 条形图 两种可切换。"""
    if not S.records:
        ui.notify("请先扫描以获取数据", type="warning")
        return
    try:
        from . import graph_view
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
                    opt = graph_view.build_graph_option(S.records, mode=mode)
                    echart_container.clear()
                    with echart_container:
                        ui.echart(opt).style("width:100%;height:75vh")

                mode_switch.on("update:model-value", lambda *_: refresh_graph())
                # 初始渲染
                with echart_container:
                    ui.echart(graph_view.build_graph_option(S.records)).style("width:100%;height:75vh")
    except Exception as exc:
        log.error("图谱渲染失败: %s", exc)
        ui.notify(f"图谱渲染失败: {exc}", type="negative")
