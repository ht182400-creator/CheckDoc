# 10 · Loop 工程化与自我迭代（MemoAlign）

> 将本项目从"一次性脚本"升级为**自我迭代的循环（Loop Engineering）"。
> 理论依据：Anthropic《Designing loops with Fable 5》提出的"五组件 + 记忆层"结构。

## 1. 为什么要 Loop Engineering
过去我们"手动 prompt" Agent 改代码；Loop Engineering 让我们**设计让 Agent 定时自我迭代的系统**：
定义目标与停止条件，Agent 在调度器上循环跑 `发现→规划→执行→验证→迭代`，直到满足停止条件。

## 2. 五组件 + 记忆层 → 本项目落地

| # | 组件 | CodeBuddy 能力 | 本项目产物 |
|---|------|---------------|-----------|
| ① | 自动化触发 | `automation_update`（recurring） | 每日定时迭代的 automation（见 §4） |
| ② | 工作树隔离 | `git worktree` | `loop/worktree.ps1` 一键建隔离分支 |
| ③ | 技能文件 | `.codebuddy/skills/` | `memoalign-loop/SKILL.md`（项目约定/陷阱） |
| ④ | 连接器 | MCP / 脚本 | `_gh_push.py`（GitHub REST API 推送） |
| ⑤ | 子代理 | `Task` 工具（code-explorer） | 验证代理独立跑 `loop/verify.py` |
| 记忆 | 状态持久化 | `.codebuddy/memory/` | `BACKLOG.md` + `MEMORY.md` |

## 2.1 关于 K3（Kimi K3）与 Loop 的关系澄清
用户最初将"K3 / Fable 5"并列为自我迭代的方法论。经联网检索确认二者属**不同层面**：

- **Fable 5 / Loop Engineering**：Anthropic 提出的**方法论**（五组件 + 记忆层），定义"如何设计让 Agent 定时自我迭代的系统"。
- **K3 = Kimi K3**：月之暗面（Moonshot AI）于 **2026-07-16** 发布的旗舰**开源模型**——2.8 万亿参数 MoE、KDA（Kimi Delta Attention）混合线性注意力 + 注意力残差、100 万 token 上下文、原生视觉理解，面向软件工程 / 深度研究 / 多模态优化，目前为全球参数最大的开源模型。它是一个**模型**，是 Loop 里"执行代理 / 子代理"可选用的**引擎**之一。

**结论**：本 Loop 架构**模型无关**。当前自动化默认由本 IDE 内置模型驱动；若将来改用 Kimi K3，只需把连接器 / 子代理的模型后端切到 K3 的 API（或本地部署的开源权重），五组件结构**无需改动**。K3 的 100 万 token 上下文与长程编码能力，对缓解"意图债务"、承载大型验证任务尤其有利。

## 3. 一次迭代的生命周期
```
automation(每日) ──▶ 加载 memoalign-loop 技能
        │
        ├─ 发现：loop/verify.py 看现状 + 读 BACKLOG.md
        ├─ 规划：从 BACKLOG 取最高优先级 1 项
        ├─ 执行：git worktree add 隔离分支 → 改代码
        ├─ 验证：派 code-explorer 子代理独立跑 loop/verify.py（不信任自己）
        ├─ 迭代：未过→回执行修复；过→commit + _gh_push.py 推送 + 打 tag
        └─ 状态：写回 BACKLOG.md / MEMORY.md
                │
                └─▶ 满足停止条件？──是──▶ 停止自动迭代，转人工
```

## 4. Automation 配置
- 类型：recurring（每日定时）
- 作用域：`d:\Work_Area\Python\checkdoc`
- 提示词：加载 `memoalign-loop` 技能，按"迭代协议"推进 1 项，验证通过后提交并推送
- 停止条件：见 `SKILL.md §6`（P2 三项完成 + 测试绿 + 文档同步 + 已推送）

## 5. 手动触发一次迭代
```powershell
cd d:\Work_Area\Python\checkdoc
pwsh loop/worktree.ps1                 # 建隔离 worktree
python loop/verify.py                  # 验证当前状态
python _gh_push.py                     # 推送（git push 失败时）
```

## 6. 关键纪律（避免循环跑偏）
- **执行与验证分离**：写代码的代理不得自己判定"完成"，必须由独立子代理验证。
- **状态外置**：所有进度写在 BACKLOG.md，不依赖对话记忆。
- **Intent Debt 锁定**：SKILL.md 里的陷阱清单写一次长期复用，禁止重新猜测。
- **失败即停**：验证未过不推送，回执行修复；连续 2 轮无进展则转人工。

## 7. 每日 09:00 自动跑一轮，跑完之后如何处理
automation 每天 09:00 被调度器唤醒，加载 `memoalign-loop` 技能后按"迭代协议"执行一轮。跑完一轮（无论成功 / 失败）的**收尾处理逻辑**如下：

### 7.1 成功路径（验证通过）
1. **提交**：`git add` 改动文件 → `git commit`（在隔离 worktree 分支 `loop/<date>` 上）。
2. **推送**：`python _gh_push.py` 走 GitHub REST API（本机 `git push` 常因网络 reset 失败，故走 API）推到 `master` 并创建新 tag `v0.0.x`。
3. **状态回写**：`BACKLOG.md` 勾掉已完成项、追加新发现；`MEMORY.md` 更新路线进度与已发布版本号。
4. **停止条件判定**：检查"P2 三项完成 + `loop/verify.py` 全绿 + `docs/` 同步 + 已推送"是否全满足。满足 → 自动化**自动停止**，转人工接管；不满足 → 次日 09:00 继续下一轮。
5. **可见性**：运行结果自动归集到 IDE 的"自动化结果 / 分类收件箱"，可在 CodeBuddy 面板查看每轮做了什么、推送了哪个 tag。

### 7.2 失败路径（验证未通过）
- 验证代理（`code-explorer` 子代理）独立跑 `loop/verify.py` 给出"未通过"结论。
- **不推送**：失败代码绝不合并 / 推送，避免污染 `master`。
- **自动修复**：回到执行阶段修复（最多再跑 2 轮）；仍失败 → 停止自动迭代，**转人工**，并在 `BACKLOG.md` 标注阻塞点。

### 7.3 纪律（不可破）
- 执行代理**不得**自己判定自己"完成"，必须由独立子代理验证。
- 验证未过绝不推送；连续 2 轮无进展即停，避免无谓消耗 token。
- 所有进度只写 `BACKLOG.md`，不依赖对话记忆（对话关了就丢）。

### 7.4 你能做什么
- 随时在 IDE 自动化面板查看运行历史与每轮结论。
- 想立刻推进一步而不等 09:00：手动执行 §5 命令，或让我"现在跑一轮"。
- 想暂停：把 automation 设为 PAUSED；想彻底停：删除 automation，或满足停止条件后它自动停。
