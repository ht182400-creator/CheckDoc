# MEMORY.md

## 项目：MemoAlign（记忆对齐分析器）
- 位置：`d:/Work_Area/Python/checkdoc`（新建于 2026-07-15）
- 定位：本地优先工具，**通用扫描根目录下任意目录的 Markdown 笔记（不限定 memory 目录）** → 归一化为表格（内容/语言范畴/类型/规避方法/严重度/来源/标签/平台），NiceGUI 交互（排序/筛选/下钻/导出/全文检索）。仅排除全局垃圾目录（node_modules/.git/.cache 等）与隐藏容器内的非 memory 噪声。
- 扩展方式：新增字段只在 `src/config.py` 的 `SCHEMA` 追加 `FieldDef`，UI 自动加列与筛选器。
- 运行：`python -m src.main`；依赖极少（仅 nicegui）。LLM 抽取默认关闭，开启需配置 `LLM_*` 与密钥环境变量 `MEMOALIGN_LLM_API_KEY`。
- 测试：`python -m unittest tests.test_pipeline`（标准库，无需 pytest）。
- 详见：`docs/README.md`（文档导航）与 `docs/00~07`。

## 改进路线（2026-07-15 评审，已融合原 M2/M3）
- **P0 (v0.2, 2.3h) ✅ 已完成**：Shell/PowerShell/Batch/Docker 语言覆盖、命令行/环境配置/兼容性类型、平台字段、重入保护、.gitignore、Shell 测试
- **P1 (v0.3, 5.4h) ✅ 已完成**：全文检索（M3）、LLM 抽取 UI 化/批量重抽（M2）、规避增强、交叉统计、缓存瘦身、CSV 含路径、截断告警
- **P2 (v0.7, 11.5h) ✅ 已完成**：✅ treemap 图谱（M3）、✅ Excel 导出、✅ 目录分组筛选、✅ 时间范围筛选、✅ 多记录抽取（按##拆分）、✅ 统计面板重构、✅ 交互式候选面板（点击加入词库）、✅ 候选发现修复、✅ 目录浏览、✅ 筛选栏紧凑化、✅ 表格分页、✅ CSV/MD 导出修复（bytes+BOM）、✅ 测试债务清零（v0.0.4，verify 全绿）、✅ LLM 质量评分（v0.0.5）、✅ 定时增量同步（v0.0.6）、✅ 代码高亮（v0.0.7：highlight.js 注入 + #detail-body 精准定位 + 离线优雅降级）。**停止条件已满足：每日 09:00 自动化下次触发时自动停止。**
- **P3 (v0.0.8) ✅ 已完成（用户手动追加）**：✅ PDF 导出（src/exporters.py build_pdf + reportlab STSong-Light 中文渲染；CSV/Excel/MD 导出重构进同一纯函数模块）、✅ 记录内编辑/修正低分（详情"✏️ 编辑"对话框写回记录+缓存并重算质量分；"修正低分"按钮按可见低分队列逐条编辑，src/record_edit.py 纯逻辑）、✅ K3 可选 LLM 后端（config.LLM_PRESETS 新增 Kimi K3：base_url=https://api.moonshot.ai/v1, model=kimi-k3；LLM 设置区"后端"下拉切换自动填充 base_url/model，复用既有 OpenAI 兼容 LLMExtractor）。verify 7 套件全绿，独立子代理审查通过。
- **P4 (v0.1.0, 2026-07-18) ✅ 已完成（第三方评审 W1-W13 整改）**：✅ ui_app.py 1380→~200 行拆分（_ui_state/_ui_helpers/_ui_filters/_ui_dialogs/_ui_actions）、✅ FileMeta 构造下沉 scanner.FileMeta.from_path（W2）、✅ 颜色/时间/阈值/上限硬编码收敛 config（W3）、✅ UI 纯逻辑单测 tests/test_ui_helpers.py(13)（W8）、✅ PDF 超大文本边界用例（W9）、✅ docs/09 与 JSON 口径统一 139（W10）、✅ 空态硬禁用按钮（W11）、✅ SKILL 停止条件对齐（W12）、✅ verify.py 固化 ui_import 冒烟 + case_library 静态检查（W13）。loop/verify.py 全绿（编译+ui_import+case_library+8 套件），独立 code-explorer 复评通过。
- **P5 (v0.1.1) ✅ 已完成（大表白屏治本）**：✅ WebSocket buffer 治标（main.py 在 `import nicegui` 前 patch `socketio.AsyncServer.__init__` 注入 `max_http_buffer_size=256MB`，常量 `config.SOCKETIO_MAX_HTTP_BUFFER_SIZE`，根因 NiceGUI 默认 1MB）；✅ 表格瘦身（`_flatten_one` 剔除 `_raw`/`_raw_preview`、TEXT 截断 200 字预览，`_flatten_records` 复用）；✅ 详情改为按 id 从服务端 `S.records` 取完整记录（缓存记录无 `_raw` 时按 `_path` 现读源文件兜底）；✅ 导出改读 `_compute_visible()` 完整可见记录（避免瘦身后丢 content）；✅ run_scan 增量扁平化 append 去 O(N²) 全量重建（每 20 文件 update 一次）。体积对比：单条 37KB→1.3KB(29.4×)，2万条旧版 723MB→显示行 24.6MB。verify ALL PASS（含 UH15-UH20，UIHelpers 16→22 / 总计 223→229）。
- **P6 (v0.1.2) ✅ 已完成（rowClick 崩溃修复）**：✅ 根因（查 NiceGUI 源码确认）：`S.table.on("rowClick", handler)` 未指定 `args`，Quasar `rowClick` 发射 `(evt, row, pageIndex)`（`quasar.umd.js:23766`），`nicegui/client.py:398-400` 仅当 `args` 长度为 1 才解包，故 `e.args` 是 3 元素列表；旧 handler 对 list 调 `.get` 崩溃 `'list' object has no attribute 'get'`。✅ 修复：`on("rowClick", ..., args=["row"])` 显式取 row 对象；抽纯函数 `_ui_helpers._parse_row_click_id(args)`（dict→id，其它返回 None 防御）；`_on_row_click` 改用它取 id 调 `_open_detail`。✅ 新增 `TestParseRowClickId`（UH21-UH24）。verify ALL PASS（UIHelpers 22→26 / 总计 229→233）。**教训：绑定 Quasar 多参事件必须显式 `args=` 指定要回传的字段，否则整包列表回传会崩。**
- 详见：`docs/08_综合评审报告.md`、`docs/11_第三方独立评审报告.md` §8
- **P7 (v0.1.3) ✅ 已完成（IME 中文检索误搜治本）**：✅ 根因（查 NiceGUI 3.14 源码确认）：Quasar `QInput` **不把** `compositionstart`/`compositionend`/`input` 作为 Python 回调转发（`widget.on("compositionstart")` 不触发、`widget.on("input")` 触发则搜索整段失灵）。故纯 Python 端永远拿不到 IME 合成状态，拼音态（如「向dao」）会直接检索导致 0 命中。✅ 正确解法（Vue3 社区标准 + NiceGUI 官方 `run_javascript` 桥接）：在客户端用原生 DOM 事件监听 `compositionstart/end`(capture 阶段)，把状态写入 `window.__memoalign_composing`；Python 端防抖 `_fire` 改为 `async`，到点时 `await ui.run_javascript("return window.__memoalign_composing === true;")` 读标志——合成中推迟、提交中文后才搜索。`IME_COMPOSITION_JS`/`_inject_ime_composition_js`/`_is_composing` 在 `src/_ui_filters.py`，`ui.timer(0.5, once=True)` 客户端连上后注入（idempotent），失败降级纯防抖（仍正确，仅偶发中间误搜）。verify ALL PASS。**教训：NiceGUI 的 `ui.input`(QInput) 只能可靠用 `update:model-value`/`on_change` 触发 Python 回调；原生 DOM 事件（input/composition*）不一定转发，要拿 IME 合成等客户端状态必须用 `ui.run_javascript` 桥接。**

## Loop Engineering（2026-07-17 搭建）
- 项目已改造为**自我迭代循环**，理论依据 Anthropic《Designing loops with Fable 5》五组件+记忆层。
- 五组件落地：① 自动化 `automation_update` 每日 09:00 触发（recurring，ACTIVE）；② `git worktree` 隔离（`loop/worktree.ps1`）；③ 技能 `.codebuddy/skills/memoalign-loop/SKILL.md`（意图债务/陷阱清单）；④ 连接器 `_gh_push.py`（GitHub REST API）；⑤ 子代理 `Task`(code-explorer) 独立验证；记忆层 `.codebuddy/memory/BACKLOG.md`+`MEMORY.md`。
- 验证代理入口：`python loop/verify.py`（编译+unittest，输出 tests/loop_verify.json，失败 exit 1）。
- 文档：`docs/10_Loop工程化与自我迭代.md`（含 §2.1 K3 关系澄清、§7 每日跑完后的处理）。
- 停止条件：P2（原三项）+ 第三方评审 W1-W13 全部完成 + verify 全绿（含 ui_import 冒烟与 case_library 静态检查）+ 文档同步 + 已推送（v0.1.0 已达）。
- **模型后端（2026-07-17 确认）**：本 Loop 架构模型无关。K3=Kimi K3 是月之暗面 2026-07-16 发布的 2.8T 开源模型（100万token上下文/原生视觉/长程编码强），是"执行/验证代理"可选引擎之一；当前自动化默认用 IDE 内置模型，未来可切 K3 API 或本地权重，五组件结构不动。
