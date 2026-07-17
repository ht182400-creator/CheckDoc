---
name: memoalign-loop
description: MemoAlign 项目的循环工程（Loop Engineering）技能。当自动化任务、定时迭代、自我改进、或任何涉及"让项目持续演进"的诉求时加载。包含构建/测试命令、已知陷阱（意图债务）、架构约束、迭代协议。
---

# MemoAlign 循环工程技能（memoalign-loop）

本技能供**循环迭代**使用：自动化任务或定时巡检加载本技能后，无需重新向 Agent 解释项目背景，
直接按"迭代协议"推进。目标是把项目从 v0.0.3 推进到"完整可用版本"（所有 P2 完成、测试绿、文档同步、已推送）。

## 1. 项目身份（一句话）
本地优先工具：扫描 `**/memory/*.md` → 归一化为结构化表格（内容/语言/类型/规避/严重度/来源/标签/平台），
NiceGUI 交互。Schema 驱动（`src/config.py` 的 `SCHEMA` 是单一真相源）。

## 2. 构建 / 测试 / 启动命令（每次迭代必跑）
```powershell
cd d:\Work_Area\Python\checkdoc
# 编译检查（禁止裸跑，先编译）
python -m py_compile src/*.py
# 回归测试（标准库 unittest，无需 pytest）
python -m unittest tests.test_pipeline -v
python -m unittest tests.test_runner -v
# 也可一键验证：python loop/verify.py
# 启动服务
python -m src.main   # http://127.0.0.1:8080
```

## 3. 已知陷阱 / 意图债务（Intent Debt，写一次长期复用）
> 这些坑已踩过，禁止 Agent 重新"自信地猜"。

- **日志规范**：禁止 `print()` 调试；统一用 `src/logger.py` 的 `log`，格式含毫秒、分级（debug/info/warning/error）。error 必须带 `traceback.format_exc()`。
- **候选发现触发条件**：`src/extractor.py` 的 `_detect_language` 仅在 `language==["通用"]`（未命中任何语言关键词）时才调用 `discover_from_text`，已匹配文件不再产生候选。**不要改回"总是触发"**，否则全加载后候选面板不清空。
- **treemap label formatter**：`graph_view.py` 中 treemap 的 `label.formatter` 必须是**字符串** `"{b|{b}}\n{c|{c} 条}"`，不是 tuple。
- **echart 容器布局**：`ui_app.py` 的 `_open_graph()` 中 `echart_container` 必须在标题 row **外部**，卡片 `height:92vh`，容器 `width:100%;height:78vh`。
- **GitHub 推送**：`git push` 在本机常因网络 reset 失败；改用 `python _gh_push.py`（走 GitHub REST API，读 `$env:GITHUB_TOKEN`）。token 已存在于环境变量。
- **测试债务的真相**：`tests/test_pipeline` 中部分 extract 返回类型断言、`tests/test_runner` 中 store 缓存格式断言，因前期"多记录抽取/缓存格式重构"已**过时**，会导致断言失败——这是测试代码未同步，不是业务 bug。迭代时若碰到，应**修复测试使其与当前代码一致**，而非改回业务代码。

## 4. 架构约束（改动前必读）
- `src/config.py` 的 `SCHEMA`：新增字段只改这里，UI 自动加列+筛选器。禁止在业务代码硬编码字段名。
- 模块分层：`scanner`（发现文件）→ `extractor`（抽取记录）→ `store`（缓存/状态）→ `ui_app`（NiceGUI 组装）→ `main`（入口）。
- 单文件 ≤500 行；超则按职责拆（通信/算法/命令/UI）。
- 改函数签名必须搜全项目同步所有调用方（用 search_content 全量查引用）。

## 5. 迭代协议（每次 loop 执行顺序）
1. **发现（discovery）**：运行 `python loop/verify.py` 看测试/编译现状；读 `.codebuddy/memory/BACKLOG.md` 取最高优先级待办；读 `MEMORY.md` 看路线。
2. **规划（planning）**：从 BACKLOG 选 1 项（默认顺序：修测试债务 → LLM质量评分 → 定时同步 → 代码高亮），列出改动文件。
3. **执行（execution）**：在**隔离 worktree** 中改代码（`git worktree add ../memoalign-loop-<date> -b loop/<date>`）。
4. **验证（verification，独立于执行）**：派 **code-explorer 子代理** 独立重读改动文件 + 跑 `loop/verify.py`，给出通过/未通过结论。禁止执行代理自己判定自己。
5. **迭代（iteration）**：验证未过 → 回到执行修复；验证过 → `git add` 相关文件 → `git commit` → 用 `_gh_push.py` 推送 + 打 tag（v0.0.x）。
6. **状态（state）**：更新 BACKLOG（勾掉完成项、追加新发现）、MEMORY（路线进度）。

## 6. 停止条件（"完整可用版本"定义）
满足以下全部即停止自动迭代，转为人工接管：
- P2 剩余 3 项全部 ✅（LLM 质量评分、定时同步、代码高亮）
- `python loop/verify.py` 全绿（含修复后的测试）
- `docs/` 与代码同步（README/架构/FAQ 无过期）
- 已通过 `_gh_push.py` 推送并打新 tag
