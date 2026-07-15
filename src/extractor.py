# encoding: utf-8
"""抽取引擎：规则抽取（离线默认）+ LLM 抽取（可选），输出统一记录。

规则抽取基于关键词命中 + 小节定位，保证无网/无密钥时可用；
LLM 抽取更准确但可插拔，失败时自动回落规则抽取。
"""
import os
import re
from typing import Dict, List

from . import config
from . import keywords_discovery as discovery
from .logger import log
from .scanner import FileMeta
from .llm_client import LLMExtractor

_llm = LLMExtractor()


def _read_text(path: str) -> str:
    """读取文件文本，编码容错（utf-8 -> gbk -> 忽略）。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read(config.READ_CHUNK_LIMIT)
    except (UnicodeDecodeError, OSError):
        try:
            with open(path, "r", encoding="gbk", errors="ignore") as f:
                return f.read(config.READ_CHUNK_LIMIT)
        except OSError as exc:
            log.warning("文件读取失败: %s | %s", path, exc)
            return ""


def _first_heading(text: str, fallback: str) -> str:
    """取首个 Markdown 标题作为内容摘要，否则回落文件名。"""
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#"):
            return s.lstrip("#").strip() or fallback
    return fallback


def _detect_language(text: str) -> List[str]:
    """按关键词命中语言范畴（可多选）。

    当无任何关键词命中时（返回["通用"]），触发候选关键词发现，
    从文本中提取未被覆盖的技术术语供用户后续确认添加。
    """
    low = text.lower()
    hits = [cat for cat, kws in config.LANGUAGE_KEYWORDS.items()
            if any(kw.lower() in low for kw in kws)]
    if not hits:
        # 无命中：触发候选发现（仅在文本含足够英文技术词时）
        if discovery.pending_for_language(low):
            try:
                discovery.discover_from_text(low)
            except Exception as exc:
                log.debug("候选发现异常（不影响抽取）: %s", exc)
        return ["通用"]
    return hits


def _detect_type(text: str) -> str:
    """按优先级命中类型，首个命中即返回。"""
    low = text.lower()
    for label, kws in config.TYPE_KEYWORDS:
        if any(kw.lower() in low for kw in kws):
            return label
    return "其他"


def _detect_platform(text: str) -> List[str]:
    """按操作系统关键词命中平台（可多选，默认跨平台）。"""
    low = text.lower()
    hits = [plat for plat, kws in config.PLATFORM_KEYWORDS.items()
            if any(kw.lower() in low for kw in kws)]
    return hits or ["跨平台"]


def _detect_severity(text: str) -> str:
    """按关键词判定严重度。"""
    if any(kw in text for kw in config.SEVERITY_KEYWORDS["高"]):
        return "高"
    if any(kw in text for kw in config.SEVERITY_KEYWORDS["低"]):
        return "低"
    return "中"


def _extract_section(text: str, header_kws: List[str]) -> str:
    """提取标题包含指定关键词的小节正文。"""
    collecting = False
    buf: List[str] = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            collecting = any(kw in line for kw in header_kws)
            continue
        if collecting:
            buf.append(line)
    return "\n".join(buf).strip()


def _extract_avoidance(text: str) -> str:
    """定位规避方法：优先小节 → 代码块 → 散列句子 → 行内模式。

    增强策略（P1-3）：
    1. 传统标题小节匹配（AVOIDANCE_HEADERS）
    2. 代码块中提取命令/解决方案（Shell 笔记常用格式）
    3. 正文中 "解决方法:" / "正确做法:" 等模式（非标题行）
    4. 正文散列句子扫描（含建议/规避关键词）
    """
    # 策略 1：标题小节匹配
    section = _extract_section(text, config.AVOIDANCE_HEADERS)
    if section:
        return section[:500]

    parts: List[str] = []

    # 策略 2：提取 Markdown 代码块中的命令（Shell 笔记常见）
    code_blocks = re.findall(r'```[\w]*\n(.*?)```', text, re.DOTALL)
    for block in code_blocks:
        # 只保留看起来像命令/配置的行
        lines = [l.strip() for l in block.splitlines()
                 if l.strip() and not l.strip().startswith('#')]
        if lines:
            parts.append("; ".join(lines[:3]))  # 最多 3 条命令

    # 策略 3：行内 "解决方法:" / "正确做法:" / "替代命令:" 模式
    inline_patterns = re.findall(
        r'(?:解决方法|正确做法|替代命令|改用|推荐用法|workaround)[：:]\s*(.+?)(?:[。\n]|$)',
        text
    )
    if inline_patterns:
        parts.extend(p.strip() for p in inline_patterns[:3])

    # 策略 4：正文散列句子扫描（扩充 Shell/CLI 常用词）
    sents = re.split(r"(?<=[。！？\n])", text)
    hits = [s.strip() for s in sents
            if any(kw in s for kw in (
                "避免", "建议", "注意", "应当", "需要", "务必", "推荐", "解法",
                "解决方法", "替代", "workaround", "改用", "正确",
            ))]
    if hits:
        parts.append(" ".join(hits))

    return " | ".join(parts)[:500]


def _rule_extract(text: str, meta: FileMeta) -> Dict:
    """规则抽取主流程：逐字段抽取并组装记录。"""
    content = _first_heading(text, meta.name)
    language = _detect_language(text)
    platform = _detect_platform(text)  # 平台检测（P0-3）
    typ = _detect_type(text)
    avoidance = _extract_avoidance(text)
    severity = _detect_severity(text)
    # 标签：语言 + 类型 + 平台（组合标签便于交叉筛选）
    tags = language + [typ] + platform
    source = f"{meta.project}/{meta.name}"
    return {
        "content": content,
        "language": language,
        "platform": platform,
        "type": typ,
        "avoidance": avoidance,
        "severity": severity,
        "source": source,
        "tags": tags,
    }


def _normalize(record: Dict, meta: FileMeta, raw: str) -> Dict:
    """补齐所有 Schema 字段默认值，并附加内部字段（路径/原文/截断标记）。"""
    for f in config.SCHEMA:
        if f.key not in record or record[f.key] in (None, ""):
            if f.ftype == config.FieldType.MULTI:
                record[f.key] = []
            elif f.ftype == config.FieldType.SELECT:
                record[f.key] = f.options[0] if f.options else ""
            else:
                record[f.key] = ""
    record["_path"] = meta.path
    record["_raw"] = raw
    # P1-7：检测文本是否被截断（抽取只读前 READ_CHUNK_LIMIT 字符）
    record["_truncated"] = len(raw) >= config.READ_CHUNK_LIMIT
    return record


def extract(meta: FileMeta, force_llm: bool = False) -> Dict:
    """对单个文件执行抽取，返回统一记录（异常隔离 + LLM 回落）。

    Args:
        meta: 扫描产出的文件元信息
        force_llm: 是否强制使用 LLM 抽取（P1-2 批量重抽用），失败后不回落规则抽取

    Returns:
        Dict: 含全部 Schema 字段 + 内部字段 _path/_raw
    """
    raw = _read_text(meta.path)
    record: Dict = {}

    # 优先 LLM（若启用且可用，或强制 LLM 模式）
    if force_llm or config.LLM_ENABLED:
        try:
            llm_out = _llm.extract(raw, config.SCHEMA)
            if isinstance(llm_out, dict):
                record = llm_out
                log.debug("LLM 抽取成功: %s", meta.path)
        except Exception as exc:
            log.warning("LLM 抽取失败: %s | %s", meta.path, exc)
            if force_llm:
                # 强制模式：失败后不回落，抛出让调用方处理
                raise

    # 规则抽取兜底（或在 LLM 关闭 + 非强制时直接走这里）
    if not record:
        record = _rule_extract(raw, meta)

    return _normalize(record, meta, raw)
