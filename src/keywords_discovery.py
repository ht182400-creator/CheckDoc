# encoding: utf-8
"""候选关键词发现：扫描时识别未被覆盖的技术术语，生成候选供用户确认。

算法策略（多源提取 + 停用词过滤 + 已有关键词去重）：
1. 反引号内命令/技术词（如 `docker-compose`、`Set-ExecutionPolicy`）
2. CamelCase/PascalCase 词（如 TimedRotatingFileHandler）
3. 全大写缩写词（2-6 字符，如 PATH、CRLF、HMR）
4. Markdown 标题中的名词短语
5. 排出常见英语停用词 + 已有关键词 + 数字
6. 按出现频次降序展示，频次低于阈值不展示
"""
import re
import traceback
from collections import Counter
from typing import List, Set, Tuple

from . import config
from . import keywords as kw_mod
from .logger import log

# 候选缓存（词 → 频次），每次扫描前清空
_candidates: Counter = Counter()

# 英语停用词（避免收集这些高频无意义词）
_STOP_WORDS: Set[str] = {
    "the", "a", "an", "is", "are", "be", "it", "in", "on", "at", "to",
    "for", "of", "and", "or", "not", "this", "that", "we", "you", "he",
    "she", "can", "will", "with", "from", "by", "as", "if", "do", "does",
    "all", "but", "has", "been", "was", "were", "have", "had", "no", "yes",
    "so", "than", "then", "only", "just", "also", "about", "into", "over",
    "after", "before", "between", "out", "up", "down", "off", "when", "where",
    "how", "what", "why", "which", "who", "would", "could", "should", "may",
    "might", "shall", "one", "two", "new", "old", "first", "last", "next",
    "file", "files", "use", "used", "using", "make", "made", "see", "get",
    "set", "add", "run", "need", "needs", "work", "works", "well", "good",
    "bad", "high", "low", "big", "small", "more", "most", "some", "any",
    "each", "every", "other", "same", "different", "too", "now", "here",
    "there", "like", "much", "many", "very", "really", "still", "back",
    "way", "part", "time", "end", "take", "let", "put", "found", "find",
    "note", "notes", "code", "test", "tests", "data", "doc", "docs",
}

# 额外排除的前缀（如版本号、哈希片段）
_EXCLUDE_PATTERNS = re.compile(r'^\d+[.\d]*$|^[a-f0-9]{8,}$|^v?\d+\.\d+')

# 筛选参数（提取为常量，避免硬编码散落）
_MIN_WORD_LEN: int = 3            # 最小词长（过滤过短词）
_MIN_FREQUENCY: int = 2           # 最小频次（低于此不展示）
_MAX_CANDIDATES: int = 50         # 最大候选数


def reset_candidates() -> None:
    """清空候选缓存（每次扫描前调用）。"""
    _candidates.clear()


def get_candidates() -> List[Tuple[str, int, str]]:
    """返回排序后的候选词列表，格式 [(词, 频次, 来源示例), ...]。

    Returns:
        List[Tuple[str, int, str]]: 按频次降序的候选词
    """
    return _candidates.most_common(_MAX_CANDIDATES)


def _is_valid_candidate(word: str) -> bool:
    """校验候选词是否有效。"""
    if len(word) < _MIN_WORD_LEN:
        return False
    if word in _STOP_WORDS:
        return False
    if word.isdigit():
        return False
    if _EXCLUDE_PATTERNS.match(word):
        return False
    return True


def discover_from_text(text: str) -> None:
    """从文件全文中发现未被现有词库覆盖的技术术语，累加到候选缓存。

    仅当该文件的 language=["通用"]（即无任何关键词命中）时才调用，
    避免对已匹配文件做无用扫描。

    Args:
        text: 文件全文（已小写）
    """
    if not text:
        return

    try:
        # 获取当前全量已知关键词用于去重
        known = kw_mod.get_all_known_keywords()

        # 策略 1：反引号内的命令/技术词（`like-this`）
        backtick_words = re.findall(r'`([^`]+)`', text)

        # 策略 2：CamelCase / PascalCase 词
        camel_words = re.findall(r'\b(?:[a-z]+(?:[A-Z][a-z]+)+|[A-Z][a-z]+(?:[A-Z][a-z]+)+)\b', text)

        # 策略 3：全大写缩写词（2-6 字符）
        upper_words = re.findall(r'\b[A-Z]{2,6}\b', text)

        # 策略 4：Markdown 标题中的名词短语
        headings = re.findall(r'^#+\s+(.+)', text, re.MULTILINE)
        heading_words: List[str] = []
        for h in headings:
            heading_words.extend(re.findall(r'\b[a-zA-Z][a-zA-Z0-9._/-]{2,}\b', h))

        # 合并去重
        all_terms: Set[str] = set()
        for word_list in [backtick_words, camel_words, upper_words, heading_words]:
            for w in word_list:
                cleaned = re.sub(r'[^a-zA-Z0-9._/-]', '', w).strip().lower()
                cleaned = cleaned.lstrip('/-._').rstrip('/-._')
                if not _is_valid_candidate(cleaned):
                    continue
                if cleaned in known:
                    continue
                # 子串去重：如果 cleaned 是已知关键词的子串或包含已知关键词，仍保留
                # （例如 "docker-compose" 已知，则 "docker" 不加入，但 "podman" 加入）
                is_sub = any(cleaned in kw or kw in cleaned for kw in known)
                if is_sub:
                    continue
                all_terms.add(cleaned)

        _candidates.update(all_terms)
    except Exception as exc:
        log.debug("候选发现异常（不影响主流程）: %s", exc)


def pending_for_language(text: str) -> bool:
    """快速判断文本是否可能有未覆盖的词（启发式，节省计算）。

    仅当文件中存在 ≥3 个英文技术词时返回 True，
    否则说明文本中文为主不触发候选发现。

    Args:
        text: 文件全文片段（前 2000 字符）

    Returns:
        bool: 是否需要触发候选发现
    """
    try:
        tech_hints = re.findall(r'\b[a-zA-Z]{3,}\b', text[:2000])
        return len(tech_hints) >= 3
    except Exception:
        return False
