# encoding: utf-8
"""NiceGUI 界面编排：构建页面布局并将控件接线到各子模块。

设计要点（拆分后）：
- 共享可变状态集中在 `_ui_state`（各子模块经 `S.xxx` 访问）。
- 纯函数辅助在 `_ui_helpers`；筛选/统计在 `_ui_filters`；对话框在 `_ui_dialogs`；
  动作/处理器在 `_ui_actions`。本文件只负责 @ui.page 路由与布局组装，不再承载业务逻辑。
- 表格列/筛选器由 config.SCHEMA 驱动（Schema 驱动，可扩展）。
"""
import os

from nicegui import ui

from . import config
from . import _ui_state as S
from . import _ui_helpers as H
from . import _ui_filters as F
from . import _ui_dialogs as D
from . import _ui_actions as A
from .logger import log


def _on_row_click(e) -> None:
    """表格行点击事件：取行 id 打开详情（详情按 id 从服务端完整记录取数）。

    S.table.on("rowClick", ..., args=["row"]) 注册时已显式只取 row 对象，
    故 e.args 即 row dict；解析交由 _ui_helpers._parse_row_click_id（含防御，
    避免早期 'list' object has no attribute 'get' 崩溃）。
    """
    rid = H._parse_row_click_id(e.args)
    if rid is not None:
        D._open_detail(rid)


@ui.page("/")
def create_ui() -> None:
    """构建页面布局（@ui.page 装饰器注册为根路由 "/"，由 NiceGUI 按需调用）。"""
    # P2-4：注入 highlight.js（详情代码块语法高亮；离线时优雅降级）
    if config.CODE_HIGHLIGHT_ENABLED:
        ui.add_head_html(H.HIGHLIGHT_HEAD_HTML)

    # 标题栏
    with ui.card().classes("w-full q-pa-md"):
        ui.label("MemoAlign · 记忆对齐分析器").classes("text-h5 text-weight-bold")
        ui.label("将任意目录的 Markdown 笔记对齐为结构化表格：排序 / 筛选 / 下钻 / 导出").classes("text-subtitle2 text-grey")

    # 路径输入 + 操作按钮
    with ui.card().classes("w-full q-pa-md"):
        with ui.row().classes("items-end gap-2 w-full"):
            S.path_input = ui.input("扫描根目录", value=config.DEFAULT_ROOT).props(
                "outlined clearable").classes("grow")
            ui.button("📁 浏览", on_click=D._open_dir_browser).props("outline")
            S.scan_btn = ui.button("扫描", on_click=A.run_scan)
            S.force_full_cb = ui.checkbox("强制全量", value=False).props(
                "dense tooltip='勾选则忽略缓存、全量重抽所有文件'")
            graph_btn = ui.button("图谱视图", on_click=D._open_graph)
            ui.button("重置筛选", on_click=F._reset_filters)
            S.export_scope = ui.select(
                options={"visible": "当前可见", "all": "全部记录"},
                value="visible",
            ).props("dense outlined tooltip='导出范围：当前可见=按筛选结果；全部记录=忽略筛选导出全部'")
            S.export_scope.style("min-width: 110px")
            csv_btn = ui.button("导出 CSV", on_click=A._export_csv)
            xlsx_btn = ui.button("导出 Excel", on_click=A._export_xlsx)
            md_btn = ui.button("导出 MD", on_click=A._export_md)
            pdf_btn = ui.button("导出 PDF", on_click=A._export_pdf)
            correct_btn = ui.button("修正低分", on_click=D._correct_low_scores).props("outline")
        S.status_label = ui.label("就绪").classes("text-caption text-grey")

        # P1-1：全文检索输入框
        with ui.row().classes("items-end gap-2 w-full q-mt-sm"):
            S.global_search_input = ui.input(
                "全文检索", placeholder="搜索全部字段及原文内容…"
            ).props("outlined clearable dense").classes("grow")
            # IME 合成安全：Quasar QInput 不把 composition/input 转发到 Python，故在客户端
            # 注入原生 composition 监听桥接 window.__memoalign_composing；防抖到点时读该
            # 标志，合成中推迟、提交中文后才检索（参考 Vue3 主流做法），规避拼音中间态误搜。
            F._attach_ime_safe_input(S.global_search_input, F._apply_filters)

        # P2-3：定时增量同步
        with ui.row().classes("items-center gap-2 w-full q-mt-sm"):
            ui.button("增量同步", on_click=A._incremental_sync).props("outline")
            S.autosync_switch = ui.switch("自动同步", value=config.AUTOSYNC_ENABLED).props("dense")
            S.autosync_switch.on("update:model-value", lambda *_: A._toggle_autosync())
            S.autosync_interval = ui.select(
                options={k: f"{int(v) // 60}分" for k, v in config.AUTOSYNC_INTERVALS.items()},
                value=config.AUTOSYNC_DEFAULT_INTERVAL,
            ).props("dense outlined").style("min-width:90px")
            S.autosync_interval.on("update:model-value", lambda *_: A._toggle_autosync())

        # W11：依赖数据存在的操作按钮，初始无数据时禁用（扫描后按结果启用）
        S.data_buttons = [csv_btn, xlsx_btn, md_btn, pdf_btn, graph_btn, correct_btn]
        for _b in S.data_buttons:
            _b.disable()

    # P1-2：LLM 抽取设置（可折叠）
    with ui.expansion("LLM 抽取设置", icon="smart_toy", value=False).classes("w-full q-mt-sm"):
        # P3：LLM 后端选择（K3 可选后端）
        with ui.row().classes("items-end gap-2 w-full"):
            S._llm_provider_select = ui.select(
                options={k: v["label"] for k, v in config.LLM_PRESETS.items()},
                value=config.LLM_DEFAULT_PROVIDER,
            ).props("dense outlined").style("min-width:220px")
            ui.label("后端").classes("text-caption text-grey")
            S._llm_provider_select.on("update:model-value", lambda *_: A._on_provider_change())
        with ui.row().classes("items-end gap-3 w-full"):
            S._llm_enabled_switch = ui.switch("启用 LLM", value=config.LLM_ENABLED).props("dense")
            S._llm_enabled_switch.on("update:model-value", lambda *_: A._update_llm_config())
            S._llm_status_label = ui.label(
                "已启用" if config.LLM_ENABLED and config.LLM_API_KEY else "未启用"
            ).classes("text-caption text-grey")
            with ui.row().classes("items-end gap-2 w-full q-mt-sm"):
                S._llm_url_input = ui.input("API 地址", value=config.LLM_BASE_URL).props(
                    "outlined dense").classes("grow")
                S._llm_model_input = ui.input("模型", value=config.LLM_MODEL).props(
                    "outlined dense").style("max-width:160px")
            with ui.row().classes("items-end gap-2 w-full q-mt-sm"):
                S._llm_key_input = ui.input(
                    "API Key", value=os.environ.get("MEMOALIGN_LLM_API_KEY", ""),
                    password=True, password_toggle_button=True,
                ).props("outlined dense").classes("grow")
                ui.button("批量 LLM 重抽", on_click=A._batch_llm_re_extract).props("outline")
                ui.button("批量质量评分", on_click=A._batch_quality_score).props("outline")

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
                            S.metric_files = val_label
                        elif ref_name == "metric_total":
                            S.metric_total = val_label
                        elif ref_name == "metric_matched":
                            S.metric_matched = val_label
                        elif ref_name == "metric_unmatched":
                            S.metric_unmatched = val_label
                        elif ref_name == "metric_quality":
                            S.metric_quality = val_label
                        else:
                            S.metric_platforms = val_label
            # 右侧 chips 区域（占满剩余空间）
            with ui.column().classes("col gap-0"):
                with ui.row().classes("items-center gap-1"):
                    ui.label("类型").classes("text-caption text-grey").style("min-width:32px")
                    S.chips_types = ui.row().classes("gap-1")
                with ui.row().classes("items-center gap-1"):
                    ui.label("语言").classes("text-caption text-grey").style("min-width:32px")
                    S.chips_langs = ui.row().classes("gap-1")
                with ui.row().classes("items-center gap-1"):
                    ui.label("平台").classes("text-caption text-grey").style("min-width:32px")
                    S.chips_platforms = ui.row().classes("gap-1")
                # 待识别行（语言="通用" 的记录，关键词未覆盖）
                with ui.row().classes("items-center gap-1"):
                    ui.label("待识别").classes("text-caption text-grey").style("min-width:32px")
                    S.chips_unmatched = ui.row().classes("gap-1")
        # 交叉统计（语言 × 类型）— 单独一行
        S.cross_stats_label = ui.markdown("").classes("text-caption q-mt-xs")

    # 候选操作行（全加载/热加载/重置 — 独立于面板，不会被 clear 删除）
    S.candidate_actions = ui.row().classes("w-full q-px-sm q-py-xs items-center gap-2").style("display:none")
    # 候选关键词面板（扫描后显示，有候选→chips，无候选→绿色完成提示）
    S.candidate_container = ui.card().classes("w-full q-pa-sm").style("display:none; background:#fff8e1")
    # 筛选栏容器
    S.filter_container = ui.element("div").classes("w-full")

    # 表格容器：sticky header + 表格内置滚动，保证表头与列严格对齐
    with ui.card().classes("w-full q-pa-none"):
        S.table = ui.table(
            columns=H._build_columns(),
            rows=[],
            row_key="id",
            pagination={"rowsPerPage": config.TABLE_DEFAULT_PAGE_SIZE, "page": 1,
                         "rowsPerPageOptions": config.TABLE_PAGE_SIZE_OPTIONS},
        ).props(
            "flat bordered separator=cell dense wrap-cells "
            "sticky-header "
            "table-style='max-height:62vh'"
        ).classes("w-full")
        # P2-1：行点击打开详情。显式 args=["row"] 让 NiceGUI 只回传 Quasar
        # rowClick 的 row 对象（默认会整包回传 [evt, row, pageIndex] 列表，导致
        # handler 把 list 当 dict 调 .get 报 AttributeError），row 始终含 id 字段。
        S.table.on("rowClick", _on_row_click, args=["row"])
        # P2-2：质量分列自定义渲染（彩色等级徽标，未评分显示灰字）
        # W3：阈值使用 config 常量，避免魔法数字散落
        S.table.add_slot("body-cell-quality_score", f"""
          <q-td :props="props">
            <template v-if="props.value == null || props.value === ''">
              <span class="text-grey">未评分</span>
            </template>
            <template v-else>
              <q-badge
                :color="props.value >= {config.QUALITY_HIGH_THRESHOLD} ? 'green' : (props.value >= {config.QUALITY_MID_THRESHOLD} ? 'orange' : 'red')">
                {{{{ props.value }}}} {{ props.value >= {config.QUALITY_HIGH_THRESHOLD} ? '高' : (props.value >= {config.QUALITY_MID_THRESHOLD} ? '中' : '低') }}
              </q-badge>
            </template>
          </q-td>
        """)

    # 详情对话框（一次构建，复用）
    S.detail_dialog = ui.dialog()
    with S.detail_dialog:
        with ui.card().classes("w-full max-w-3xl"):
            ui.label("笔记详情").classes("text-h6")
            S.meta_md = ui.markdown()
            # P2-4：包一层带 id 的容器，便于 JS 精准定位代码块做高亮
            with ui.column().props("id=detail-body").classes("w-full"):
                S.body_md = ui.markdown()
            with ui.row().classes("w-full justify-end q-mt-sm"):
                ui.button("✏️ 编辑", on_click=lambda: D._open_edit(S.current_detail_row)).props("outline")
                ui.button("关闭", on_click=S.detail_dialog.close).props("flat")
