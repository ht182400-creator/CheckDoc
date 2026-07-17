# MEMORY.md

## 项目：MemoAlign（记忆对齐分析器）
- 位置：`d:/Work_Area/Python/checkdoc`（新建于 2026-07-15）
- 定位：本地优先工具，扫描 `**/memory/*.md` → 归一化为表格（内容/语言范畴/类型/规避方法/严重度/来源/标签/平台），NiceGUI 交互（排序/筛选/下钻/导出/全文检索）。
- 扩展方式：新增字段只在 `src/config.py` 的 `SCHEMA` 追加 `FieldDef`，UI 自动加列与筛选器。
- 运行：`python -m src.main`；依赖极少（仅 nicegui）。LLM 抽取默认关闭，开启需配置 `LLM_*` 与密钥环境变量 `MEMOALIGN_LLM_API_KEY`。
- 测试：`python -m unittest tests.test_pipeline`（标准库，无需 pytest）。
- 详见：`docs/README.md`（文档导航）与 `docs/00~07`。

## 改进路线（2026-07-15 评审，已融合原 M2/M3）
- **P0 (v0.2, 2.3h) ✅ 已完成**：Shell/PowerShell/Batch/Docker 语言覆盖、命令行/环境配置/兼容性类型、平台字段、重入保护、.gitignore、Shell 测试
- **P1 (v0.3, 5.4h) ✅ 已完成**：全文检索（M3）、LLM 抽取 UI 化/批量重抽（M2）、规避增强、交叉统计、缓存瘦身、CSV 含路径、截断告警
- **P2 (v0.6, 11.5h) 🔄 进行中**：✅ treemap 图谱（M3）、✅ Excel 导出、✅ 目录分组筛选、✅ 时间范围筛选、✅ 多记录抽取（按##拆分）、✅ 统计面板重构、✅ 交互式候选面板（点击加入词库）、✅ 候选发现修复、✅ 目录浏览、✅ 筛选栏紧凑化、✅ 表格分页、✅ CSV/MD 导出修复（bytes+BOM）、✅ 测试债务清零（v0.0.4，verify 全绿）、✅ LLM 质量评分（v0.0.5）、✅ 定时增量同步（v0.0.6：src/sync.py + 增量同步按钮 + 自动同步开关 ui.timer）；📋 代码高亮
- 详见：`docs/08_综合评审报告.md`

## Loop Engineering（2026-07-17 搭建）
- 项目已改造为**自我迭代循环**，理论依据 Anthropic《Designing loops with Fable 5》五组件+记忆层。
- 五组件落地：① 自动化 `automation_update` 每日 09:00 触发（recurring，ACTIVE）；② `git worktree` 隔离（`loop/worktree.ps1`）；③ 技能 `.codebuddy/skills/memoalign-loop/SKILL.md`（意图债务/陷阱清单）；④ 连接器 `_gh_push.py`（GitHub REST API）；⑤ 子代理 `Task`(code-explorer) 独立验证；记忆层 `.codebuddy/memory/BACKLOG.md`+`MEMORY.md`。
- 验证代理入口：`python loop/verify.py`（编译+unittest，输出 tests/loop_verify.json，失败 exit 1）。
- 文档：`docs/10_Loop工程化与自我迭代.md`（含 §2.1 K3 关系澄清、§7 每日跑完后的处理）。
- 停止条件：P2 三项完成 + verify 全绿 + 文档同步 + 已推送。
- **模型后端（2026-07-17 确认）**：本 Loop 架构模型无关。K3=Kimi K3 是月之暗面 2026-07-16 发布的 2.8T 开源模型（100万token上下文/原生视觉/长程编码强），是"执行/验证代理"可选引擎之一；当前自动化默认用 IDE 内置模型，未来可切 K3 API 或本地权重，五组件结构不动。
