# encoding: utf-8
"""抽取引擎：规则抽取（离线默认）+ LLM 抽取（可选），输出统一记录。

规则抽取基于关键词命中 + 小节定位，保证无网/无密钥时可用；
LLM 抽取更准确但可插拔，失败时自动回落规则抽取。
"""
import os
import re
from typing import Dict, List, Tuple

from . import config
from . import keywords_discovery as discovery
from .logger import log
from .scanner import FileMeta
from .llm_client import LLMExtractor

_llm = LLMExtractor()


def _read_text(path: str) -> str:
    """读取文件文本，编码容错（utf-8 -> gbk -> 忽略）。"""
    log.debug("_read_text 入口 | path=%s", path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read(config.READ_CHUNK_LIMIT)
            log.debug("_read_text 出口 | len=%d, encoding=utf-8", len(text))
            return text
    except (UnicodeDecodeError, OSError):
        try:
            with open(path, "r", encoding="gbk", errors="ignore") as f:
                text = f.read(config.READ_CHUNK_LIMIT)
                log.debug("_read_text 出口(回退) | len=%d, encoding=gbk", len(text))
                return text
        except OSError as exc:
            log.warning("文件读取失败: %s | %s", path, exc)
            log.debug("_read_text 出口(空)")
            return ""


def _first_heading(text: str, fallback: str) -> str:
    """取首个 Markdown 标题 + 紧跟的正文摘要（前 2 段），否则回落文件名。"""
    log.debug("_first_heading 入口 | fallback=%s, text_len=%d", fallback, len(text))
    lines = text.splitlines()
    title = ""
    title_end = -1
    # 1) 找第一个标题行
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("#"):
            title = s.lstrip("#").strip()
            title_end = i
            break
    # 2) 取标题后的前 2 个非空非标题段
    body_lines: List[str] = []
    for line in lines[title_end + 1:]:
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        # 跳过代码块边界
        if s.startswith("```"):
            continue
        body_lines.append(s)
        if len(body_lines) >= 2:
            break
    # 3) 拼接：标题 + 正文摘要
    if title and body_lines:
        return f"{title} | {' '.join(body_lines)[:400]}"
    if title:
        return title
    return fallback


def _detect_language(text: str) -> List[str]:
    """按关键词命中语言范畴（可多选）。

    当无任何关键词命中时（返回["通用"]），触发候选关键词发现，
    从文本中提取未被覆盖的技术术语供用户后续确认添加。
    """
    log.debug("_detect_language 入口 | text_len=%d", len(text))
    low = text.lower()
    hits = [cat for cat, kws in config.LANGUAGE_KEYWORDS.items()
            if any(kw.lower() in low for kw in kws)]
    # 仅当未命中任何语言关键词时触发候选发现，避免已匹配记录继续产生候选
    if not hits:
        try:
            discovery.discover_from_text(text)
        except Exception as exc:
            log.debug("候选发现异常（不影响抽取）: %s", exc)
    log.debug("_detect_language 出口 | hits=%s", hits or ["通用"])
    return hits or ["通用"]


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


def _is_field_section(title: str) -> bool:
    """判断小节标题是否是"字段"（如"规避方法"、"解决方法"等）而非独立问题。

    只合并 AVOIDANCE_HEADERS 中的标题（明确是解决方案/建议的小节）；
    其他 ## 标题（如"问题"、"配置"）一律视为独立主条目。
    """
    for kw in config.AVOIDANCE_HEADERS:
        if kw in title:
            return True
    return False


def _split_sections(text: str) -> List[Tuple[str, str, str]]:
    """按 Markdown 二级标题拆分文档为多个小节。

    Returns:
        List[(section_title, section_body, kind)], kind ∈ {"main", "field", "intro"}
        - "intro"：H1 与第一个 ## 之间（H1 后无 ## 时的整段）
        - "main"：独立的 ## 问题小节
        - "field"：字段型 ## 小节（"规避方法"等），用于合并到前一个 main 段
    """
    lines = text.splitlines()
    # 找 H1
    h1_title = ""
    body_start = 0
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("# ") and not s.startswith("## "):
            h1_title = s[2:].strip()
            body_start = i + 1
            break
    # 找所有 ## 段
    section_starts: List[int] = []
    section_titles: List[str] = []
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("## "):
            level = 0
            for ch in s:
                if ch == "#":
                    level += 1
                else:
                    break
            if level >= 2:
                section_starts.append(i)
                section_titles.append(s[level:].strip())
    if not section_starts:
        # 整篇作为一段
        fallback = h1_title if h1_title else "(无标题)"
        body = "\n".join(lines[body_start:]).strip()
        if body:
            return [(fallback, body, "intro")]
        return []
    parts: List[Tuple[str, str, str]] = []
    # 前言（短前言合并到第一个 main 段，跳过独立条目）
    intro_text = ""
    if body_start < section_starts[0]:
        intro_text = "\n".join(lines[body_start:section_starts[0]]).strip()
    # ## 段
    for idx, start in enumerate(section_starts):
        end = section_starts[idx + 1] if idx + 1 < len(section_starts) else len(lines)
        body = "\n".join(lines[start + 1:end]).strip()
        title = section_titles[idx]
        kind = "field" if _is_field_section(title) else "main"
        parts.append((title, body, kind))
    return parts


def _rule_extract_section(section_text: str, file_title: str, file_path: str,
                          section_title: str) -> Dict:
    """对单个小节做规则抽取。"""
    # content = 小节标题 + 前 2 段正文
    body_lines = []
    for line in section_text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("```"):
            continue
        body_lines.append(s)
        if len(body_lines) >= 2:
            break
    if section_title and body_lines:
        content = f"{section_title} | {' '.join(body_lines)[:400]}"
    elif section_title:
        content = section_title
    else:
        content = file_title
    # 字段抽取（只基于本小节文本，更精准）
    language = _detect_language(section_text)
    platform = _detect_platform(section_text)
    typ = _detect_type(section_text)
    avoidance = _extract_avoidance(section_text)
    severity = _detect_severity(section_text)
    # 若本节没找到规避方法，回落用全文（避免漏掉）
    if not avoidance and section_text != section_text:
        avoidance = _extract_avoidance(section_text)
    tags = language + [typ] + platform
    # 来源：完整文件路径 # 小节名（便于定位）
    if section_title and section_title not in ("前言", file_title, "(无标题)"):
        source = f"{file_path}  #  {section_title}"
    else:
        source = file_path
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
    log.debug("_normalize 入口 | type=%s", record.get("type", "?"))
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


def extract(meta: FileMeta, force_llm: bool = False) -> List[Dict]:
    """对单个文件执行抽取，按 ## 小节返回多条记录（异常隔离 + LLM 回落）。

    Args:
        meta: 扫描产出的文件元信息
        force_llm: 是否强制使用 LLM 抽取（P1-2 批量重抽用），失败后不回落规则抽取

    Returns:
        List[Dict]: 每个小节一条记录，每条含全部 Schema 字段 + 内部字段 _path/_raw
    """
    log.debug("extract 入口 | path=%s, force_llm=%s", meta.path, force_llm)
    raw = _read_text(meta.path)
    file_title = _first_heading(raw, meta.name)

    # 优先 LLM（若启用且可用，或强制 LLM 模式）
    llm_records: List[Dict] = []
    if force_llm or config.LLM_ENABLED:
        try:
            llm_out = _llm.extract(raw, config.SCHEMA)
            if isinstance(llm_out, dict):
                llm_records = [llm_out]
            elif isinstance(llm_out, list):
                llm_records = llm_out
            log.debug("LLM 抽取成功: %s, 记录数=%d", meta.path, len(llm_records))
        except Exception as exc:
            log.warning("LLM 抽取失败: %s | %s", meta.path, exc)
            if force_llm:
                raise

    if llm_records:
        # LLM 模式：使用 LLM 返回的记录
        return [_normalize(r, meta, raw) for r in llm_records]

    # 规则抽取：按 ## 小节拆分，field 小节合并到前一个 main 小节
    parts = _split_sections(raw)
    # 若完全没有 ## 段，或只有 field/intro 没有 main，整篇作为 1 条
    has_main = any(k == "main" for _, _, k in parts)
    if not parts or not has_main:
        return [_normalize(_rule_extract_section(raw, file_title, meta.path, ""), meta, raw)]

    # 提取 intro 段（如果有）
    intro_text = ""
    main_parts = []
    for sec_title, sec_body, kind in parts:
        if kind == "intro":
            intro_text = sec_body
        else:
            main_parts.append((sec_title, sec_body, kind))

    out: List[Dict] = []
    current: Dict = {}  # 累积当前 main 小节的字段
    first_main = True
    log.debug("extract 开始处理 | sections=%d, has_main=%s", len(main_parts), has_main)
    for sec_title, sec_body, kind in main_parts:
        if kind == "field":
            # 字段小节：合并到当前 main 段（若无 main 段则丢弃）
            if current:
                current["_raw"] = (current.get("_raw", "") + "\n\n## " + sec_title + "\n" + sec_body)
            continue
        # main 段：先刷出之前的累积
        if current:
            out.append(_normalize(current, meta, raw))
            current = {}
        # 启动新记录
        current = _rule_extract_section(sec_body, file_title, meta.path, sec_title)
        # 第一个 main 段：把 intro 前言合并进来（但太短就忽略）
        if first_main and intro_text and len(intro_text) > 20:
            current["_raw"] = (intro_text + "\n\n## " + sec_title + "\n" + sec_body)
        first_main = False
    # 收尾
    if current:
        out.append(_normalize(current, meta, raw))
    log.debug("extract 出口 | 路径=%s, 记录数=%d", meta.path, len(out))
    return out
