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
- **P2 (v0.4, 11.5h) 🔄 进行中**：✅ treemap 图谱（M3）、✅ Excel 导出、✅ 目录分组筛选、✅ 时间范围筛选、✅ 多记录抽取（按##拆分）、✅ 统计面板重构、✅ 交互式候选面板（点击加入词库）、✅ 候选发现修复、✅ 目录浏览、✅ 筛选栏紧凑化、✅ 表格分页、✅ CSV/MD 导出修复（bytes+BOM）；📋 LLM 质量评分、📋 定时同步、📋 代码高亮
- 详见：`docs/08_综合评审报告.md`
