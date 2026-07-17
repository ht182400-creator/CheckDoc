# encoding: utf-8
"""UI 动作层：导出、LLM 重抽、质量评分、增量同步、候选关键词、扫描。

依赖：共享状态（_ui_state）、纯函数辅助（_ui_helpers）、筛选层（_ui_filters）。
"""
import asyncio
import os
import traceback
from collections import defaultdict

from nicegui import ui

from . import config, scanner, extractor, store, quality_scorer, sync
from . import exporters, record_edit
from . import keywords as kw_mod
from . import keywords_discovery as discovery
from . import _ui_state as S
from . import _ui_helpers as H
from . import _ui_filters as F
from .logger import log


# ---------------------------------------------------------------------------
# 导出动作
# ---------------------------------------------------------------------------
def _export_csv() -> None:
    """导出当前表格可见记录为 CSV（经 exporters 生成字节流）。"""
    if not S.table or not S.table.rows:
        ui.notify("表格无数据可导出", type="warning")
        return
    content = exporters.build_csv(S.table.rows)
    log.info("CSV导出: 记录数=%d, 字节数=%d", len(S.table.rows), len(content))
    ui.download(content, "memoalign.csv", "text/csv; charset=utf-8")
    ui.notify(f"已导出 CSV：{len(S.table.rows)} 条记录", type="positive")


def _export_xlsx() -> None:
    """导出当前表格可见记录为 Excel（失败自动回落 CSV）。"""
    if not S.table or not S.table.rows:
        ui.notify("表格无数据可导出", type="warning")
        return
    try:
        content = exporters.build_xlsx(S.table.rows)
    except RuntimeError:
        ui.notify("未安装 openpyxl，已改为导出 CSV。可执行 pip install openpyxl 启用 Excel 导出", type="warning")
        _export_csv()
        return
    except Exception as exc:
        log.error("Excel 导出失败: %s", exc)
        ui.notify(f"Excel 导出失败: {exc}", type="negative")
        return
    ui.download(content, "memoalign.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    ui.notify("已导出 Excel", type="positive")


def _export_md() -> None:
    """按类型分组导出 Markdown 摘要（经 exporters 生成字节流）。"""
    if not S.table or not S.table.rows:
        ui.notify("表格无数据可导出", type="warning")
        return
    content = exporters.build_md(S.table.rows)
    log.info("MD导出: 记录数=%d, 字节数=%d", len(S.table.rows), len(content))
    ui.download(content, "memoalign.md", "text/markdown; charset=utf-8")
    ui.notify(f"已导出 Markdown：{len(S.table.rows)} 条记录", type="positive")


def _export_pdf() -> None:
    """导出当前表格可见记录为 PDF（含中文；依赖 reportlab）。"""
    if not S.table or not S.table.rows:
        ui.notify("表格无数据可导出", type="warning")
        return
    try:
        content = exporters.build_pdf(S.table.rows)
    except RuntimeError:
        ui.notify("未安装 reportlab，无法导出 PDF。可执行 pip install reportlab 启用", type="negative")
        return
    except Exception as exc:
        log.error("PDF 导出失败: %s", exc)
        ui.notify(f"PDF 导出失败: {exc}", type="negative")
        return
    ui.download(content, "memoalign.pdf", "application/pdf")
    ui.notify(f"已导出 PDF：{len(S.table.rows)} 条记录", type="positive")
    log.info("PDF导出: 记录数=%d, 字节数=%d", len(S.table.rows), len(content))


# ---------------------------------------------------------------------------
# LLM 配置与后端切换
# ---------------------------------------------------------------------------
def _update_llm_config() -> None:
    """从 UI 控件同步 LLM 配置到 config 模块（P1-2）。"""
    if S._llm_url_input is not None:
        config.LLM_BASE_URL = S._llm_url_input.value.strip() or config.LLM_BASE_URL
    if S._llm_key_input is not None:
        config.LLM_API_KEY = S._llm_key_input.value.strip() or config.LLM_API_KEY
    if S._llm_model_input is not None:
        config.LLM_MODEL = S._llm_model_input.value.strip() or config.LLM_MODEL
    if S._llm_enabled_switch is not None:
        config.LLM_ENABLED = S._llm_enabled_switch.value
    # 更新状态提示
    if S._llm_status_label is not None:
        if config.LLM_ENABLED and config.LLM_API_KEY:
            S._llm_status_label.text = f"已启用 → {config.LLM_MODEL}"
            S._llm_status_label.classes("text-caption text-positive")
        elif config.LLM_ENABLED:
            S._llm_status_label.text = "已启用但未配置密钥"
            S._llm_status_label.classes("text-caption text-warning")
        else:
            S._llm_status_label.text = "未启用"
            S._llm_status_label.classes("text-caption text-grey")


def _on_provider_change() -> None:
    """LLM 后端切换：按预设填充 base_url/model 并刷新配置。"""
    if S._llm_provider_select is None:
        return
    preset = config.LLM_PRESETS.get(S._llm_provider_select.value)
    if not preset:
        return
    config.LLM_BASE_URL = preset["base_url"]
    config.LLM_MODEL = preset["model"]
    if S._llm_url_input is not None:
        S._llm_url_input.value = preset["base_url"]
    if S._llm_model_input is not None:
        S._llm_model_input.value = preset["model"]
    _update_llm_config()
    ui.notify(f"已切换后端：{preset['label']}", type="info")
    log.info("LLM 后端切换: %s", preset["label"])


# ---------------------------------------------------------------------------
# 批量 LLM 重抽（P1-2）
# ---------------------------------------------------------------------------
async def _batch_llm_re_extract() -> None:
    """批量 LLM 重抽：用 LLM 对所有记录重新抽取。

    先同步 LLM 配置，再逐条重抽（缓存无效直接覆盖），带进度提示。
    """
    if S._scanning:
        ui.notify("操作正在进行中，请等待完成", type="warning")
        return
    S._scanning = True
    if S.scan_btn is not None:
        S.scan_btn.disable()

    try:
        _update_llm_config()
        if not config.LLM_API_KEY:
            ui.notify("请先输入有效的 API Key", type="negative")
            return
        if not S.records:
            ui.notify("请先扫描以获取记录", type="warning")
            return

        total = len(S.records)
        ui.notify(f"开始 LLM 重抽，共 {total} 篇…", type="info")
        S.status_label.text = f"LLM 重抽中… 0/{total}"
        log.info("开始 LLM 批量重抽: 记录数=%d", total)

        cache = store.load_cache()
        for i, r in enumerate(S.records):
            meta_path = r.get("_path", "")
            if not meta_path or not os.path.isfile(meta_path):
                continue
            try:
                # W2：FileMeta 构造下沉到 scanner.FileMeta.from_path
                meta = scanner.FileMeta.from_path(meta_path)
                new_records = extractor.extract(meta, force_llm=True)
                if not new_records:
                    continue
                store.put_all(cache, meta, new_records)
                # LLM 模式：只替换第 1 条；其余保持原样
                new_records[0]["id"] = r.get("id", i + 1)
                S.records[i] = new_records[0]
            except Exception as exc:
                log.warning("LLM 重抽异常（跳过该条）: %s\n%s", meta_path, traceback.format_exc())
            if (i + 1) % 3 == 0:
                S.status_label.text = f"LLM 重抽中… {i + 1}/{total}"
                await asyncio.sleep(0.1)

        store.save_cache(cache)
        F._build_filter_bar()
        F._update_stats(S.records)
        S.table.rows = H._flatten_records(S.records)
        S.status_label.text = f"LLM 重抽完成 · 共 {len(S.records)} 篇"
        ui.notify(f"LLM 重抽完成，共 {len(S.records)} 篇", type="positive")
        log.info("LLM 批量重抽结束: 成功=%d", len(S.records))
    except Exception as exc:
        log.error("LLM 批量重抽异常: %s\n%s", exc, traceback.format_exc())
        ui.notify(f"LLM 重抽失败: {exc}", type="negative")
    finally:
        S._scanning = False
        if S.scan_btn is not None:
            S.scan_btn.enable()


# ---------------------------------------------------------------------------
# 批量质量评分（P2-2）
# ---------------------------------------------------------------------------
async def _batch_quality_score() -> None:
    """批量质量评分：对当前所有记录打分（LLM 语义或离线启发式）。"""
    if S._scanning:
        ui.notify("操作正在进行中，请等待完成", type="warning")
        return
    S._scanning = True
    if S.scan_btn is not None:
        S.scan_btn.disable()

    try:
        _update_llm_config()
        if not S.records:
            ui.notify("请先扫描以获取记录", type="warning")
            return

        use_llm = bool(config.LLM_ENABLED) and bool(config.LLM_API_KEY)
        if not use_llm:
            ui.notify("未启用 LLM，将使用离线启发式评分", type="info")
        total = len(S.records)
        S.status_label.text = f"质量评分中… 0/{total}"
        log.info("开始批量质量评分: 记录数=%d, 模式=%s", total, "LLM" if use_llm else "heuristic")

        # 1) 就地打分
        quality_scorer.score_records(S.records, llm=use_llm)

        # 2) 按路径分组写回缓存（保留 _raw_preview 供详情展示）
        cache = store.load_cache()
        by_path: dict = defaultdict(list)
        for r in S.records:
            by_path[r.get("_path", "")].append(r)
        for path, recs in by_path.items():
            if not path or not os.path.isfile(path):
                continue
            try:
                for r in recs:
                    # 缓存写入前补全 _raw（来自预览），使详情展示不丢失
                    if not r.get("_raw"):
                        r["_raw"] = r.get("_raw_preview", "")
                # W2：FileMeta 构造下沉到 scanner.FileMeta.from_path
                meta = scanner.FileMeta.from_path(path)
                store.put_all(cache, meta, recs)
            except Exception as exc:
                log.warning("质量分写回缓存异常（跳过该文件）: %s\n%s", path, traceback.format_exc())

        store.save_cache(cache)
        F._build_filter_bar()
        F._update_stats(S.records)
        S.table.rows = H._flatten_records(S.records)
        S.status_label.text = f"质量评分完成 · 共 {len(S.records)} 篇"
        ui.notify(f"质量评分完成：{len(S.records)} 篇（{'LLM' if use_llm else '启发式'}）", type="positive")
        log.info("批量质量评分结束: 成功=%d", len(S.records))
    except Exception as exc:
        log.error("批量质量评分异常: %s\n%s", exc, traceback.format_exc())
        ui.notify(f"质量评分失败: {exc}", type="negative")
    finally:
        S._scanning = False
        if S.scan_btn is not None:
            S.scan_btn.enable()


# ---------------------------------------------------------------------------
# 增量同步（P2-3）
# ---------------------------------------------------------------------------
async def _incremental_sync() -> None:
    """增量同步：对当前根目录重扫，对比前后差异并通知。"""
    if S._scanning:
        return  # 静默跳过，避免定时器与手动扫描竞态
    # 快照旧记录（按 _path）
    old_snapshot = [dict(r) for r in S.records]
    await run_scan()
    diff = sync.compute_diff(old_snapshot, S.records)
    summary = sync.summarize(diff)
    if diff["added"] or diff["changed"] or diff["removed"]:
        ui.notify(f"增量同步：{summary}", type="info")
        log.info("增量同步完成: %s", summary)
    else:
        ui.notify("增量同步：无变化", type="positive")


def _toggle_autosync() -> None:
    """自动同步开关：开启则启动 NiceGUI 定时器，关闭则取消。"""
    try:
        if S.autosync_switch is not None and S.autosync_switch.value:
            interval = config.AUTOSYNC_INTERVALS.get(
                S.autosync_interval.value if S.autosync_interval else config.AUTOSYNC_DEFAULT_INTERVAL,
                config.AUTOSYNC_INTERVALS[config.AUTOSYNC_DEFAULT_INTERVAL],
            )
            if S._sync_timer is not None:
                S._sync_timer.cancel()
            # ui.timer 接受协程回调；周期性触发增量同步
            S._sync_timer = ui.timer(interval, _incremental_sync)
            ui.notify(f"已启用自动同步（每 {interval // 60} 分钟）", type="positive")
            log.info("自动同步已启用: 间隔=%d秒", interval)
        else:
            if S._sync_timer is not None:
                S._sync_timer.cancel()
                S._sync_timer = None
            ui.notify("已关闭自动同步", type="warning")
            log.info("自动同步已关闭")
    except Exception as exc:
        log.error("切换自动同步异常: %s", exc)
        ui.notify(f"自动同步切换失败: {exc}", type="negative")


# ---------------------------------------------------------------------------
# 候选关键词面板（P1 热加载 / 点击加入词库）
# ---------------------------------------------------------------------------
def _refresh_candidates() -> None:
    """刷新候选关键词面板：操作按钮在独立行（不被 clear 影响）。"""
    if S.candidate_container is None or S.candidate_actions is None:
        return
    # 防止 chip 回调内部 clear 导致"parent element deleted"
    if S._candidate_updating:
        return
    candidates = discovery.get_candidates()
    S.candidate_actions.clear()
    S.candidate_actions.style("display:flex")
    # 操作按钮行（独立，不会被候选面板 clear 删除）
    with S.candidate_actions:
        ui.button("全加载", on_click=_add_all_candidates, icon="download").props("dense outline color=orange")
        ui.button("清空待分类", on_click=_clear_pending_keywords).props("dense outline")
        ui.button("热加载", on_click=_hot_reload_keywords).props("dense")
        ui.button("重置", on_click=_reset_keywords_default).props("dense outline")
        if not candidates:
            ui.icon("check_circle", color="green", size="sm")
            ui.label("✅ 全部关键词已匹配").classes("text-body2 text-positive")
    # 候选面板：只放 chips
    S.candidate_container.style("display:block")
    S.candidate_container.clear()
    if candidates:
        with S.candidate_container:
            with ui.row().classes("items-center gap-2"):
                ui.icon("lightbulb", color="orange", size="sm")
                ui.label(f"候选关键词（{len(candidates)} 个）— 点击加入词库").classes("text-body2 text-weight-medium")
            with ui.row().classes("w-full gap-1 flex-wrap q-mt-xs"):
                for word, freq in candidates[:config.CANDIDATE_DISPLAY_MAX]:  # W3：展示上限收敛为常量
                    label = f"{word}({freq})"
                    chip = ui.chip(label, removable=True, color="orange")
                    chip.props("dense square clickable")
                    chip.on("remove", lambda w=word: _add_candidate_keyword(w))
                    chip.on("click", lambda w=word: _add_candidate_keyword(w))
    log.info("候选面板已刷新: %d关键词", len(candidates))


async def _add_candidate_keyword(word: str) -> None:
    """将候选关键词加入默认分类并热加载 + 重扫。"""
    S._candidate_updating = True
    try:
        ok = kw_mod.add_keyword("language_keywords", config.LANG_PENDING, word)
        if ok:
            kw_mod.reload()
            store.reset()
            await run_scan()
            ui.notify(f"已添加关键词并重扫: {word}", type="positive")
        else:
            ui.notify(f"关键词已存在: {word}", type="warning")
    except Exception as exc:
        ui.notify(f"添加失败: {exc}", type="negative")
        log.error("添加候选关键词失败: %s", exc)
    finally:
        S._candidate_updating = False
        _refresh_candidates()  # 安全更新面板（chip 回调已结束）


async def _add_all_candidates() -> None:
    """一键加载所有候选词：先清旧批、再写入新批、自动重扫。"""
    candidates = discovery.get_candidates()
    if not candidates:
        ui.notify("没有候选关键词", type="warning")
        return
    S._candidate_updating = True
    try:
        kw_mod.clear_category("language_keywords", config.LANG_PENDING)
        added = 0
        for word, _ in candidates:
            if kw_mod.add_keyword("language_keywords", config.LANG_PENDING, word):
                added += 1
        kw_mod.reload()
        store.reset()
        await run_scan()
        ui.notify(f"已加载 {added} 个关键词，已匹配↑ 待识别↓", type="positive")
        log.info("全加载候选关键词: %d个", added)
    except Exception as exc:
        ui.notify(f"加载失败: {exc}", type="negative")
        log.error("全加载候选关键词失败: %s", exc)
    finally:
        S._candidate_updating = False
        _refresh_candidates()


async def _clear_pending_keywords() -> None:
    """一键清空"通用（待分类）"分类下的所有关键词，并重扫。"""
    try:
        removed = kw_mod.clear_category("language_keywords", config.LANG_PENDING)
        # 立即清空候选缓存与面板，给用户即时反馈
        discovery.reset_candidates()
        _refresh_candidates()
        store.reset()
        await run_scan()
        ui.notify(f"已清空'待分类'，移除 {removed} 个关键词并重扫", type="positive")
        log.info("清空待分类关键词: 移除%d个", removed)
    except Exception as exc:
        ui.notify(f"清空失败: {exc}", type="negative")
        log.error("清空待分类失败: %s", exc)


async def _hot_reload_keywords() -> None:
    """热加载关键词：清空缓存 + 重新抽取，让统计数字立即反映新关键词。"""
    try:
        kw_mod.reload()
        log.info("用户触发关键词热加载")
        store.reset()
        if S.records:  # 已有数据 → 自动重扫
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
        store.reset()
        if S.records:
            ui.notify("关键词已恢复，正在重新抽取…", type="info")
            await run_scan()
        else:
            ui.notify("关键词已恢复为默认", type="positive")
    except FileNotFoundError:
        ui.notify("未找到 Git，请确认已安装", type="negative")
    except Exception as exc:
        ui.notify(f"恢复异常: {exc}", type="negative")
        log.error("恢复关键词失败: %s", exc)


# ---------------------------------------------------------------------------
# 扫描主流程
# ---------------------------------------------------------------------------
async def run_scan() -> None:
    """扫描 → 抽取（增量缓存）→ 渲染表格与筛选栏。

    内置重入保护：_scanning 为 True 时拒绝重复触发，防止协程竞态。
    """
    # 重入保护（P0-6）—— 防止并发扫描导致 records/cache 数据竞态
    if S._scanning:
        ui.notify("扫描正在进行中，请等待完成", type="warning")
        return
    S._scanning = True
    if S.scan_btn is not None:
        S.scan_btn.disable()

    try:
        root = (S.path_input.value or "").strip() or config.DEFAULT_ROOT
        if not os.path.isdir(root):
            ui.notify(f"目录不存在：{root}", type="negative")
            S.status_label.text = "就绪 · 目录不存在"
            return

        ui.notify("开始扫描…", type="info")
        S.status_label.text = "扫描中…"
        S.table.rows = []
        S.records.clear()
        discovery.reset_candidates()
        # 强制清空文件缓存，确保抽取逻辑变更后不会读到旧缓存（导致候选发现不执行）
        store.reset()
        await asyncio.sleep(0.1)

        cache = store.load_cache()
        metas = scanner.scan_memory_md(root)
        total = len(metas)
        # 更新"文件"指标（仅在首次/重置扫描时设置，不被筛选过滤）
        if S.metric_files is not None:
            S.metric_files.text = f"{total}"
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
                    S.records.append(rec)
            except Exception as exc:
                log.error("处理文件异常，已跳过: %s\n%s", meta.path, traceback.format_exc())
                placeholder = {f.key: (["通用"] if f.ftype == FieldType.MULTI else
                                       (f.options[0] if f.options else ""))
                               for f in config.SCHEMA}
                placeholder.update({"content": "解析失败", "source": f"{meta.project}/{meta.name}",
                                    "_path": meta.path, "_raw": "", "id": i, "_mtime": meta.mtime})
                S.records.append(placeholder)
            if i % 5 == 0:
                S.status_label.text = f"扫描中 {i}/{total}"
                await asyncio.sleep(0.1)

        store.save_cache(cache)
        F._build_filter_bar()
        F._update_stats(S.records)
        _refresh_candidates()
        S.table.rows = H._flatten_records(S.records)
        S.status_label.text = f"就绪 · 共 {len(S.records)} 篇"
        ui.notify(f"扫描完成，共 {len(S.records)} 篇", type="positive")
        log.info("扫描结束: 记录数=%d", len(S.records))
    finally:
        S._scanning = False
        if S.scan_btn is not None:
            S.scan_btn.enable()
        # W11：扫描结束后按是否有数据启用/禁用依赖数据的按钮
        _set_data_buttons_enabled(bool(S.records))


# ---------------------------------------------------------------------------
# W11：空数据态硬禁用依赖数据的按钮
# ---------------------------------------------------------------------------
def _set_data_buttons_enabled(enabled: bool) -> None:
    """按是否有数据启用/禁用导出、图谱、修正低分等按钮。"""
    for b in (S.data_buttons or []):
        if b is None:
            continue
        try:
            if enabled:
                b.enable()
            else:
                b.disable()
        except Exception as exc:  # 控件可能已被销毁
            log.debug("切换按钮可用态失败（忽略）: %s", exc)
