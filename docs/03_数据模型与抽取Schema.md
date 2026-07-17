# 03 数据模型与抽取 Schema

> 视角：数据分析师 + 架构师

## 1. 核心实体

### 1.1 FileMeta（扫描产物）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `path` | str | 文件绝对路径 |
| `name` | str | 文件名（去扩展名） |
| `project` | str | 所属上级目录名（用于"来源"分组） |
| `mtime` | float | 修改时间（缓存键） |
| `size` | int | 字节数 |

### 1.2 Record（对齐后记录）

由 `config.SCHEMA` 定义字段集合，统一为 `Dict[str, Any]`：

| 字段 key | 标签 | 类型 | 可筛选 | 说明 |
| --- | --- | --- | --- | --- |
| `content` | 内容 | text | 是 | 笔记主旨/问题概述 |
| `language` | 语言范畴 | multi | 是 | Python/JS/TS/Go/Rust/Shell/PowerShell/Batch/Docker/Git/通用/其他 |
| `platform` | 平台 | multi | 是 | Windows/Linux/macOS/跨平台 |
| `type` | 类型 | select | 是 | 问题/陷阱/最佳实践/规范/经验/发布/环境配置/命令行/兼容性/其他 |
| `avoidance` | 规避方法 | text | 是 | 如何规避/建议 |
| `severity` | 严重度 | select | 是 | 高/中/低 |
| `source` | 来源 | text | 是 | 项目名 + 文件名 |
| `tags` | 标签 | multi | 是 | 派生标签（语言 + 类型 + 平台组合） |

## 2. Schema 定义（config.SCHEMA）

```python
@dataclass
class FieldDef:
    key: str            # 字段键（表格列 field）
    label: str          # 中文表头
    ftype: str          # 'text' | 'select' | 'multi'
    filterable: bool    # 是否生成筛选器
    width: str          # 列宽（CSS）
    options: List[str]  # select/multi 的候选值
    extractor: str      # 规则抽取标识
```

新增字段示例（零代码改 UI）：

```python
FieldDef("owner", "负责人", FieldType.TEXT, filterable=True)
```

## 3. 规则抽取映射（KEYWORD_MAPS）

关键词从 `src/keywords_data.json` 加载（纯 JSON 文件，支持热加载）。`extractor` 使用关键词命中法，保证离线可用：

| 目标字段 | 关键词（命中即归类，完整列表见 JSON 文件） |
| --- | --- |
| `language=Python` | python, pip, conda, venv, .py, pytorch |
| `language=JS/TS` | javascript, js, ts, node, npm, vite, react, vue, electron |
| `language=Shell/Bash` | bash, zsh, shell, .sh, chmod, awk, sed |
| `language=PowerShell` | powershell, pwsh, .ps1, cmdlet |
| `language=Batch/CMD` | cmd, batch, .bat, .cmd, dos, rmdir |
| `language=Docker` | docker, container, dockerfile, compose |
| `language=Git/GitHub` | github, .git, git clone, pr, pull request |
| `type=陷阱` | 陷阱, 坑, 避坑, 踩坑 |
| `type=命令行` | 命令, cmd, shell, powershell, 执行失败, 参数错误 |
| `type=环境配置` | 安装, 卸载, 环境变量, PATH, registry, setup |
| `type=兼容性` | 兼容, 跨平台, 编码, crlf, lf |
| `type=问题` | 修复, bug, 错误, 失败, 异常, 报错 |
| `platform=Windows` | windows, powershell, cmd, .bat, .ps1, 注册表 |
| `platform=Linux` | linux, ubuntu, apt, bash, systemd |
| `platform=macOS` | macos, mac, darwin, brew |

> 新增关键词：编辑 `keywords_data.json` → 点 UI「热加载关键词」→ 即时生效，无需重启。
> 命中多条时取首个匹配；无命中回落到"通用/其他/中/跨平台"。
> 无命中时自动触发候选发现，收集未覆盖的技术术语展示在候选面板。

## 4. 候选发现引擎（keywords_discovery.py）

当文件的 language="通用"（无任何关键词命中），自动从文本中提取：
- 反引号内的命令/技术词（如 `docker-compose`）
- CamelCase/PascalCase 词（如 TimedRotatingFileHandler）
- 全大写缩写词（如 PATH、HMR）
- 标题中的名词短语

候选词按频次降序展示，供用户确认后添加到 `keywords_data.json`。

## 5. LLM 抽取（可选）

当 `LLM_ENABLED=True` 时，`LLM Client` 向 OpenAI 兼容接口发送：

- system：要求按 Schema 输出 JSON（字段 key 与类型一致）；
- user：文件全文 + Schema 描述；
- 解析 JSON → 校验字段 → 回填 Record。

LLM 失败自动回落规则抽取（保证稳定）。
