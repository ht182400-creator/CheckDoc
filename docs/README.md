# MemoAlign · 记忆对齐分析器 — 文档中心

> 角色视角：产品经理 / 架构师 / 数据分析师 / 代码实现专家 / UI 专家 / 全栈高级工程师
> 目标：将分散在**任意目录的 Markdown 笔记**（如 `.codebuddy/memory/`、各项目下的 `.md`，通用、不限定目录名）中的知识，对齐（归一化）为统一结构化表格，支持表头排序、多列筛选、详情下钻与导出，实现可扩展、稳定、快速、美观、强可操作。

## 文档导航（按角色推荐阅读路径）

| 角色 | 必读 | 参考 |
| --- | --- | --- |
| 产品经理 | [01 需求规格](01_需求规格说明书.md) · [00 概述](00_项目概述与路线图.md) | [05 UI 交互](05_UI交互与体验设计.md) |
| 架构师 | [02 架构设计](02_系统架构设计.md) · [03 数据模型](03_数据模型与抽取Schema.md) | [04 接口配置](04_接口与配置说明.md) |
| 数据分析师 | [03 数据模型](03_数据模型与抽取Schema.md) · [06 测试](06_质量保障与测试方案.md) | [00 概述](00_项目概述与路线图.md) |
| 代码实现专家 | [02 架构](02_系统架构设计.md) · [04 接口配置](04_接口与配置说明.md) | 源码 `src/` |
| UI 专家 | [05 UI 交互](05_UI交互与体验设计.md) · [01 需求](01_需求规格说明书.md) | 源码 `src/ui_app.py` + `src/_ui_state.py`/`_ui_helpers.py`/`_ui_filters.py`/`_ui_dialogs.py`/`_ui_actions.py` |
| 全栈工程师 | [07 部署运行](07_部署与运行手册.md) · [02~05 全部] | 全仓 |

## 核心文档索引

- [00 项目概述与路线图](00_项目概述与路线图.md)
- [01 需求规格说明书](01_需求规格说明书.md)
- [02 系统架构设计](02_系统架构设计.md)
- [03 数据模型与抽取 Schema](03_数据模型与抽取Schema.md)
- [04 接口与配置说明](04_接口与配置说明.md)
- [05 UI 交互与体验设计](05_UI交互与体验设计.md)
- [06 质量保障与测试方案](06_质量保障与测试方案.md)
- [07 部署与运行手册](07_部署与运行手册.md)
- [08 综合评审报告](08_综合评审报告.md)

## 仓库结构

```
checkdoc/
├── docs/                 # 项目管理文档（本目录）
├── src/                  # 源码（见 02 架构设计）
│   ├── config.py         # 全局配置、字段 Schema、各类常量（可扩展核心 + 常量收敛）
│   ├── logger.py         # 日志（毫秒级 + 每日轮转，双输出）
│   ├── scanner.py        # 通用采集器：流式扫描任意目录 MD（scan_iter/scan/FileMeta.from_path）
│   ├── extractor.py      # 抽取引擎（规则 + LLM 可插拔，按 ## 拆分多记录）
│   ├── llm_client.py     # LLM 适配（OpenAI 兼容，可选）
│   ├── store.py          # 增量缓存/索引（mtime 判断；put_all/get_cached_records/reset）
│   ├── keywords.py       # 关键词加载/热加载/添加（读 keywords_data.json）
│   ├── keywords_discovery.py # 候选发现引擎
│   ├── quality_scorer.py # 质量评分（LLM 或离线启发式 + 等级映射）
│   ├── exporters.py      # 导出纯函数（CSV/Excel/MD/PDF）
│   ├── record_edit.py    # 记录编辑纯逻辑（merge_edit/is_low_score）
│   ├── graph_view.py     # 图谱视图（treemap/bar/network 聚合）
│   ├── sync.py           # 定时增量同步（compute_diff/summarize）
│   ├── main.py           # 入口（import nicegui 前 patch socketio 缓冲上限）
│   ├── ui_app.py         # NiceGUI 页面组装（仅 @ui.page + 布局 + 控件接线）
│   ├── _ui_state.py      # UI 共享可变状态（S.* 单一存放点）
│   ├── _ui_helpers.py    # UI 纯函数层（列生成/扁平化/查找/时间判定，可单测）
│   ├── _ui_filters.py    # 筛选栏构建 / 过滤逻辑 / 统计面板更新
│   ├── _ui_dialogs.py    # 对话框（详情/编辑/目录浏览/图谱）
│   └── _ui_actions.py    # 动作/处理器（导出/LLM重抽/质量评分/同步/扫描主流程）
├── requirements.txt
└── README.md
```

## 关键链接

- 运行入口：`python -m src.main`
- 默认扫描根（示例）：`D:\Work_Area\AI`（初始示例值，可在 UI 中修改；扫描为通用行为，递归查找该根下**任意目录**的 `.md`，不限定 `memory` 目录）
- 匹配规则：**递归查找根目录下任意目录的 `.md`**（不再限定 `memory` 目录，做到通用）；仅排除 ① 全局垃圾目录（node_modules/.git/.cache 等）② 隐藏容器（`.codebuddy`/`.cursor` 等）内的非 `memory` 噪声。特定场景仍可用 `scan_memory_md` 退回只认 `memory` 目录。
