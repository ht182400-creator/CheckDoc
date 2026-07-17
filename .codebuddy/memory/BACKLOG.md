# MemoAlign 迭代状态板（State Layer）

> 这是循环工程的"状态层"：存在于对话窗口之外的持久化看板。每次 loop 迭代先读这里，结束写回这里。
> 停止条件见 SKILL.md §6。满足即停自动迭代。

## 当前版本
- v0.1.0（2026-07-18 推送：P2 架构整改 W1-W13 全量完成 —— ui_app.py 1380→~200 行拆分、FileMeta 下沉、硬编码收敛、测试缺口补齐、案例库同步静态检查固化，loop/verify.py ALL PASS）

## 停止条件（P2-W1~W13）：✅ 已满足（架构拆分 + 测试绿 + 文档同步 + 已推送）
> P2 全部完成（原 P2-3 项 + 第三方评审 W1-W13）。每日 09:00 自动化将在下次触发时读到本看板 P2 全绿而**自动停止**；如需继续演进，需重新定义新的迭代目标并更新本看板。

## 待办（按优先级，✅=完成 📋=待做 🔄=进行中）
| 优先级 | 项 | 状态 | 说明 |
| --- | --- | --- | --- |
| 1 | 修复过时测试（test_pipeline / test_runner） | ✅ | 多记录抽取+缓存格式重构后测试已同步，loop/verify.py 全绿 |
| 2 | P2-LLM 质量评分 | ✅ | 离线启发式评分（字段完整度）+ LLM 语义评分（启用且配密钥时）；质量分列/等级徽标/质量筛选/批量评分按钮/平均质量分指标/导出含质量分 |
| 3 | P2-定时同步 | ✅ | 新增 src/sync.py（compute_diff 按 _path+mtime 判新增/变更/移除）+ "增量同步"按钮 + 自动同步开关（ui.timer，5/15/30/60 分可选） |
| 4 | P2-代码高亮 | ✅ | 详情页 Markdown 代码块语法高亮（highlight.js 注入 + 精准定位 #detail-body 代码块；离线优雅降级） |
| 5 | P3-PDF 导出 | ✅ | 新增 src/exporters.py（纯函数 build_pdf 用 reportlab 内置 CID 字体 STSong-Light 渲染中文）；UI 按钮"导出 PDF"；CSV/Excel/MD 导出重构为同一模块 |
| 6 | P3-记录内编辑 / 修正低分 | ✅ | 详情页"✏️ 编辑"打开按 Schema 生成的编辑对话框，保存写回记录+缓存并重算质量分；"修正低分"按钮按当前可见低分队列逐条编辑（保存并下一条） |
| 7 | P3-K3 可选 LLM 后端 | ✅ | config.LLM_PRESETS 新增 Kimi K3（base_url=https://api.moonshot.ai/v1, model=kimi-k3）；LLM 设置区新增"后端"下拉，切换自动填充 base_url/model 并复用既有 LLMExtractor |

## 已完成（v0.0.3 及之前）
- ✅ 图谱 treemap/条形图、候选关键词面板、多记录抽取、统计面板重构
- ✅ Excel/CSV/MD 导出、目录分组/时间筛选、表格分页、候选发现修复
- ✅ P0（Shell/PowerShell/Batch/Docker 语言覆盖）、P1（全文检索/LLM抽取UI化）
- ✅ v0.0.4：测试债务清零（44 项失败 → 0），修复 5 类断言过时（extract 返回列表、store records 结构、_rule_extract→_rule_extract_section、_first_heading 摘要、Graph treemap/network 重构）

## 最近一轮迭代记录
- 2026-07-15：v0.0.3 发布（图谱+候选面板+多记录抽取+统计重构+导出修复）
- 2026-07-17（上午）：搭建 Loop Engineering 结构（Skill + BACKLOG + verify + worktree + 自动化每日09:00）
- 2026-07-17（下午）：手动推进第一轮迭代——修复测试债务。根因：extract() 返回 List[Dict]、store.put 缓存改 records[]、_rule_extract 重命名、_first_heading 加正文摘要、Graph 重构 treemap/network。改动 tests/test_pipeline.py / test_runner.py / test_data.json。独立子代理审查 + verify 全绿。commit → _gh_push.py 推送 + tag v0.0.4。
- 2026-07-17（晚）：用户要求"不等 9 点，现在开始自动化演进"。第二轮迭代实现 P2-2 LLM 质量评分：新增 src/quality_scorer.py（heuristic + LLM 双模式）、llm_client.score()、ui_app 质量分列/等级徽标 slot/质量筛选/批量评分按钮/平均质量分指标/导出含质量分、run_scan 自动启发式评分。新增 tests/test_quality.py 并纳入 loop/verify.py 套件。独立子代理审查通过 + verify 全绿 → 提交 → _gh_push.py 推送 + tag v0.0.5。
- 2026-07-17（晚）：第三轮迭代实现 P2-3 定时增量同步：新增 src/sync.py（compute_diff 按 _path+mtime 判新增/变更/移除）、config 自动同步间隔常量、ui_app "增量同步"按钮 + 自动同步开关（ui.timer 5/15/30/60 分）+ 间隔下拉。新增 tests/test_sync.py 并纳入 loop/verify.py 套件。独立子代理审查通过 + verify 全绿 → 提交 → _gh_push.py 推送 + tag v0.0.6。仅剩 P2-4 代码高亮。
- 2026-07-17（晚）：第四轮（最后一轮）迭代实现 P2-4 代码高亮：详情页 Markdown 代码块经 highlight.js（CDN）语法高亮，#detail-body 容器精准定位、offline 优雅降级；新增 tests/test_highlight.py 并纳入 loop/verify.py 套件。**P2 四项全部完成**，loop/verify.py 全绿 → 提交 → _gh_push.py 推送 + tag v0.0.7。停止条件已满足，每日 09:00 自动化将在下次触发时自动停止。
- 2026-07-17（深夜）：用户追加三个需求，手动推进 v0.0.8：① 导出 PDF（src/exporters.py build_pdf + reportlab STSong-Light 中文渲染；CSV/Excel/MD 导出重构进同一模块）；② 记录内编辑/修正低分（详情页"✏️ 编辑"对话框写回记录+缓存并重算质量分；"修正低分"按钮按可见低分队列逐条编辑，src/record_edit.py 提供纯逻辑）；③ K3 接入为可选 LLM 后端（config.LLM_PRESETS 新增 Kimi K3，LLM 设置区"后端"下拉切换自动填充 base_url/model）。新增 tests/test_exporters.py + tests/test_record_edit.py 并纳入 loop/verify.py（编译+7 套件全绿）。独立 code-explorer 子代理审查通过（无阻断项）→ 提交 → _gh_push.py 推送 + tag v0.0.8。
- 2026-07-18：用户触发 P2（第三方评审 W1-W13 全量整改）。主代理执行：ui_app.py(1380行) 拆分为 `_ui_state`+`_ui_helpers`+`_ui_filters`+`_ui_dialogs`+`_ui_actions` 五模块（≤500 行）；W2 `scanner.FileMeta.from_path` 下沉 FileMeta 构造；W3 颜色/时间/阈值/上限硬编码收敛 config；W8 新增 tests/test_ui_helpers.py(13)；W9 新增 test_pdf_huge_text_not_crash；W10 docs/09 与 JSON 统一口径 139；W11 空态硬禁用按钮；W12 SKILL.md 停止条件对齐；W13 verify.py 固化 case_library 静态检查（+ui_import 冒烟，8 套件）。2 个独立 code-explorer 复评通过；复评中修复 `_ui_state.py` 初次写入为空 + create_ui 指标循环遗漏 metric_quality 两缺陷。loop/verify.py 全绿 → _gh_push.py 推送 + tag v0.1.0（P2 全完成，停止条件满足）。

## 已知阻塞 / 风险
- 本机 `git push` 网络不稳，统一走 `_gh_push.py`（GitHub API）
- 测试债务是"测试代码过时"而非业务 bug，修复方向是同步测试而非回退业务
- 子代理（code-explorer）无命令执行能力，验证命令需主代理补跑闭环
- **2026-07-17 深夜补丁**：`docs/09_测试案例库.md` 此前停在 v2.0（仅 JSON 139 项），Loop 8 轮新增的 5 个 Python 套件（46 用例）只纳入 verify 未回填文档——已补到 v3.0（总 185 项）。根因：收尾只更新状态类文档漏了案例库。已在 SKILL.md 迭代协议强制"案例库同步"为阻断项。
- **2026-07-17 深夜：第三方独立评审（5 子代理 + 主代理核实）→ 整体不通过**。产物 `docs/11_第三方独立评审报告.md`。暴露 3 个阻断项：**B1** 详情编辑按钮闭包/未定义 `row` 失效（ui_app.py:1372）、**B2** PDF 导出未 XML 转义遇 `&<>` 崩溃（exporters.py:137-139）、**B3** `_gh_push.py:157` 非 UTF-8 读取致整轮推送失败。另 13 个 WARN（架构拆分/硬编码/裸except/测试缺口/文档口径）。**待修复 B1/B2/B3 后复评。**

## 待修复缺陷（第三方评审，按优先级）— ✅ 已全部修复
| 优先级 | 项 | 位置 | 状态 |
| --- | --- | --- | --- |
| P0 | B1 详情编辑按钮失效 | ui_app.py | ✅ 已修复 + 复评 PASS（v0.0.9） |
| P0 | B2 PDF 特符崩溃 | exporters.py | ✅ 已修复 + 复评 PASS（v0.0.9） |
| P0 | B3 推送 GBK 失败 | _gh_push.py | ✅ 已修复 + 复评 PASS（v0.0.9） |
| P1 | W4 硬编码 9 处 | config.py 常量化 | ✅ 已修复 + 复评 PASS（v0.0.9） |
| P1 | W5 裸 except | keywords_discovery.py:175 | ✅ 经核实为**误报**（实为 `except Exception:`），无需修 |
| P1 | W6 print | logger.py / _gh_push.py | ✅ 已修复（v0.0.9） |
| P2 | W1 ui_app.py 超 500 行 | 拆分为 5 子模块 | ✅ 已修复（v0.1.0，1380→~200 行） |
| P2 | W2 UI 构造 FileMeta | scanner.FileMeta.from_path | ✅ 已修复（v0.1.0） |
| P2 | W3 枚举/颜色/阈值硬编码 | 收敛 config 常量 | ✅ 已修复（v0.1.0） |
| P2 | W7 巨型函数+全局态 | 拆分 + 集中 _ui_state | ✅ 已修复（v0.1.0） |
| P2 | W8 ui_app 4 交互函数无测试 | tests/test_ui_helpers.py | ✅ 已修复（v0.1.0，13 用例） |
| P2 | W9 build_pdf 超大文本无边界 | test_pdf_huge_text_not_crash | ✅ 已修复（v0.1.0） |
| P2 | W10 文档口径矛盾 | docs/09 与 JSON 统一为 139 | ✅ 已修复（v0.1.0） |
| P2 | W11 空态仅软提示 | 初始禁用 + 扫描后启用 | ✅ 已修复（v0.1.0） |
| P2 | W12 SKILL 停止条件对齐 | SKILL.md §5/§6 | ✅ 已修复（v0.1.0） |
| P2 | W13 案例库同步仅人工查 | verify.py case_library 静态检查 | ✅ 已修复（v0.1.0） |

> 复评：2026-07-18 授权触发 P2 后，主代理执行 + 2 个独立 `code-explorer` 子代理复评，**全部维度通过**，无遗留真实 bug。`loop/verify.py` 编译 + UI 导入冒烟 + 案例库静态检查 + 8 套件 ALL PASS。详见 `docs/11_第三方独立评审报告.md` §8。
