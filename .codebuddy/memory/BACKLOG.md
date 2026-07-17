# MemoAlign 迭代状态板（State Layer）

> 这是循环工程的"状态层"：存在于对话窗口之外的持久化看板。每次 loop 迭代先读这里，结束写回这里。
> 停止条件见 SKILL.md §6。满足即停自动迭代。

## 当前版本
- v0.0.6（已推送 GitHub，P2-3 定时增量同步完成，loop/verify.py 全绿）

## 待办（按优先级，✅=完成 📋=待做 🔄=进行中）
| 优先级 | 项 | 状态 | 说明 |
| --- | --- | --- | --- |
| 1 | 修复过时测试（test_pipeline / test_runner） | ✅ | 多记录抽取+缓存格式重构后测试已同步，loop/verify.py 全绿 |
| 2 | P2-LLM 质量评分 | ✅ | 离线启发式评分（字段完整度）+ LLM 语义评分（启用且配密钥时）；质量分列/等级徽标/质量筛选/批量评分按钮/平均质量分指标/导出含质量分 |
| 3 | P2-定时同步 | ✅ | 新增 src/sync.py（compute_diff 按 _path+mtime 判新增/变更/移除）+ "增量同步"按钮 + 自动同步开关（ui.timer，5/15/30/60 分可选） |
| 4 | P2-代码高亮 | 📋 | 详情页 Markdown/代码高亮 |

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

## 已知阻塞 / 风险
- 本机 `git push` 网络不稳，统一走 `_gh_push.py`（GitHub API）
- 测试债务是"测试代码过时"而非业务 bug，修复方向是同步测试而非回退业务
- 子代理（code-explorer）无命令执行能力，验证命令需主代理补跑闭环
