# encoding: utf-8
"""全局配置：目录、抽取字段 Schema、扫描与抽取参数（单一真相源）。

设计约束（来自项目规范）：
- 所有魔法数字/字符串/路径提取到本文件命名常量（UPPER_SNAKE_CASE + 注释）。
- 表格列、筛选器、抽取目标全部由 SCHEMA 驱动，新增字段 = 改配置、零代码改 UI。
- 关键词数据从 keywords_data.json 加载（支持热加载，无需重启应用）。
"""
from dataclasses import dataclass, field
from typing import List

from . import keywords as _kw_loader

# ---------------------------------------------------------------------------
# 路径与扫描配置
# ---------------------------------------------------------------------------
# 默认扫描根目录（UI 可覆盖，可任意指定）
DEFAULT_ROOT: str = r"D:\Work_Area\AI"

# 目标子目录名：递归查找所有名为该名的目录
MEMORY_DIR_NAME: str = "memory"

# 支持的文件扩展名（小写）
MD_EXTENSIONS: tuple = (".md", ".markdown")

# 缓存目录与文件（基于 path+mtime 的增量缓存，加速重扫）
CACHE_DIR: str = ".cache"
CACHE_FILE: str = "memory_index.json"

# 扫描/抽取超时与上限（防止超大文件拖垮主流程）
MAX_FILE_BYTES: int = 2 * 1024 * 1024  # 单文件最大 2MB，超出截断
READ_CHUNK_LIMIT: int = 200_000        # 抽取时读取的最大字符数

# ---------------------------------------------------------------------------
# LLM 抽取（可选，OpenAI 兼容；默认关闭，保证离线可用）
# ---------------------------------------------------------------------------
LLM_ENABLED: bool = False
LLM_BASE_URL: str = "https://api.openai.com/v1"
LLM_API_KEY: str = ""          # 建议通过环境变量 MEMOALIGN_LLM_API_KEY 注入
LLM_MODEL: str = "gpt-4o-mini"
LLM_TIMEOUT_SEC: int = 30      # 网络请求超时

# ---------------------------------------------------------------------------
# LLM 后端预设（P3：K3 作为可选后端）
# ---------------------------------------------------------------------------
# 各预设为 OpenAI 兼容协议；Kimi K3（月之暗面）API 兼容 OpenAI 格式，
# 切换后复用既有 LLMExtractor（/chat/completions + json_object）即可。
LLM_PRESETS: dict = {
    "openai":  {"label": "OpenAI", "base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
    "kimi_k3": {"label": "Kimi K3（月之暗面）", "base_url": "https://api.moonshot.ai/v1", "model": "kimi-k3"},
}
LLM_DEFAULT_PROVIDER: str = "openai"  # 默认后端（UI 可切到 kimi_k3）

# ---------------------------------------------------------------------------
# 质量评分（P2-2，LLM 质量评分 / 置信度）
# ---------------------------------------------------------------------------
QUALITY_SCORE_KEY: str = "quality_score"   # 记录内质量分字段名（0-100，缺失/None=未评分）
QUALITY_HIGH_THRESHOLD: int = 80           # ≥ 该值判"高"
QUALITY_MID_THRESHOLD: int = 60            # 该值~HIGH 判"中"，< 该值判"低"
QUALITY_TIER_NONE: str = "未评分"           # 未评分等级文字
QUALITY_TIER_LOW: str = "低"               # 低分等级文字
QUALITY_TIER_MID: str = "中"               # 中分等级文字
QUALITY_TIER_HIGH: str = "高"              # 高分等级文字
# 启发式评分各维度权重（heuristic_score 累加用，总和=QUALITY_FULL_SCORE）
QUALITY_WEIGHT_CONTENT: int = 20     # 内容非空
QUALITY_WEIGHT_AVOIDANCE: int = 20   # 规避方法非空
QUALITY_WEIGHT_SEVERITY: int = 15    # 严重度为有效选项
QUALITY_WEIGHT_LANGUAGE: int = 20    # 语言已匹配（非"通用"）
QUALITY_WEIGHT_TYPE: int = 15        # 类型已匹配（非"其他"）
QUALITY_WEIGHT_TAGS: int = 10        # 标签非空
QUALITY_FULL_SCORE: int = 100        # 满分（累加上限）
# 导出时附加的非 Schema 字段（质量分 + 原始路径）
EXTRA_EXPORT_FIELDS: List[str] = [QUALITY_SCORE_KEY, "_path"]

# ---------------------------------------------------------------------------
# 定时增量同步（P2-3）
# ---------------------------------------------------------------------------
AUTOSYNC_ENABLED: bool = False                          # 是否默认开启自动同步
# 自动同步间隔选项（UI 下拉值 -> 秒）；默认 15 分钟
AUTOSYNC_INTERVALS: dict = {"5m": 300, "15m": 900, "30m": 1800, "60m": 3600}
AUTOSYNC_DEFAULT_INTERVAL: str = "15m"                  # 默认间隔 key

# ---------------------------------------------------------------------------
# 代码高亮（P2-4，详情页 Markdown 代码块语法高亮）
# ---------------------------------------------------------------------------
CODE_HIGHLIGHT_ENABLED: bool = True     # 是否启用详情代码块高亮（依赖 highlight.js）
# highlight.js 主题（github 浅色，离线时优雅降级为纯文本代码块）
CODE_HIGHLIGHT_THEME: str = "github"
# highlight.js CDN 版本（注入 <link>/<script> 时使用）
HIGHLIGHTJS_CDN_VERSION: str = "11.9.0"
# 表格分页配置（NiceGUI table pagination）
TABLE_DEFAULT_PAGE_SIZE: int = 50
TABLE_PAGE_SIZE_OPTIONS: list = [20, 50, 100, 0]
# 时间换算常量（增量同步按时间范围过滤时用）
SECONDS_PER_DAY: int = 86400

# ---------------------------------------------------------------------------
# 字段类型
# ---------------------------------------------------------------------------
class FieldType:
    """字段类型枚举：决定表格渲染与筛选控件形态。"""
    TEXT = "text"      # 文本：关键字输入筛选
    SELECT = "select"  # 单选枚举：下拉单选筛选
    MULTI = "multi"    # 多选枚举：下拉多选筛选


@dataclass
class FieldDef:
    """字段定义：Schema 驱动的核心数据结构。

    Attributes:
        key: 字段键（表格列 field，须唯一）
        label: 中文表头
        ftype: 字段类型（FieldType）
        filterable: 是否在筛选栏生成筛选器
        width: 列宽（CSS，如 "40%" / "120px"）
        options: 枚举候选值（select/multi 使用）
        extractor: 规则抽取标识（extractor 据此选择抽取逻辑）
    """
    key: str
    label: str
    ftype: str = FieldType.TEXT
    filterable: bool = True
    width: str = "auto"
    options: List[str] = field(default_factory=list)
    extractor: str = ""


# ---------------------------------------------------------------------------
# 默认 Schema（可扩展：在此增删字段即可在 UI 生效）
# ---------------------------------------------------------------------------
# 枚举候选（提取为常量，避免硬编码散落）
# 语言范畴 —— 覆盖主流编程语言 + Shell/CLI 领域 + 版本管理
LANG_OPTIONS: List[str] = [
    "Python", "JavaScript/TS", "Go", "Rust",
    "Shell/Bash", "PowerShell", "Batch/CMD",
    "Docker", "Git/GitHub",
    "通用", "其他",
]
# 类型 —— 新增命令行/环境配置/兼容性，覆盖 Shell/DOS 开发场景
TYPE_OPTIONS: List[str] = [
    "问题", "陷阱", "最佳实践", "规范", "经验", "发布",
    "环境配置", "命令行", "兼容性",
    "其他",
]
SEVERITY_OPTIONS: List[str] = ["高", "中", "低"]
# 平台 —— 同一问题可能只影响特定操作系统
PLATFORM_OPTIONS: List[str] = ["Windows", "Linux", "macOS", "跨平台"]

SCHEMA: List[FieldDef] = [
    FieldDef("source", "来源", FieldType.TEXT, width="24%", extractor="source"),
    FieldDef("content", "内容", FieldType.TEXT, width="22%", extractor="content"),
    FieldDef("avoidance", "规避方法", FieldType.TEXT, width="18%", extractor="avoidance"),
    FieldDef("language", "语言范畴", FieldType.MULTI, width="8%", options=LANG_OPTIONS, extractor="language"),
    FieldDef("platform", "平台", FieldType.MULTI, width="7%", options=PLATFORM_OPTIONS, extractor="platform"),
    FieldDef("type", "类型", FieldType.SELECT, width="7%", options=TYPE_OPTIONS, extractor="type"),
    FieldDef("severity", "严重度", FieldType.SELECT, width="5%", options=SEVERITY_OPTIONS, extractor="severity"),
    FieldDef("tags", "标签", FieldType.MULTI, width="9%", extractor="tags"),
]

# 主键字段（用于详情定位与去重）
ID_FIELD: str = "source"

# ---------------------------------------------------------------------------
# 规则抽取关键词映射 —— 从 keywords_data.json 加载（支持热加载，无需重启应用）
# ---------------------------------------------------------------------------
# 以下变量在模块导入时从 JSON 初始化一次；后续可通过 keywords.reload() 热更新。
LANGUAGE_KEYWORDS: dict = _kw_loader.load_language_keywords()
TYPE_KEYWORDS: List[tuple] = _kw_loader.load_type_keywords()
PLATFORM_KEYWORDS: dict = _kw_loader.load_platform_keywords()
SEVERITY_KEYWORDS: dict = _kw_loader.load_severity_keywords()
AVOIDANCE_HEADERS: List[str] = _kw_loader.load_avoidance_headers()
