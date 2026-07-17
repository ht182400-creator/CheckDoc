# encoding: utf-8
"""关键词加载器：从 JSON 数据文件读取，支持热加载与动态添加。

设计要点：
- 关键词与代码分离（keywords_data.json 为纯数据，不依赖 Python 语法）。
- reload() 热加载：读取 JSON → 更新 config 模块全局变量，无需重启应用。
- add_keyword() 动态添加：用户确认候选词 → 写入 JSON → 更新内存。
- 模块级入口函数 get_all_known_keywords() 供候选发现模块使用。
"""
import json
import os
import traceback
from typing import Dict, List, Set, Tuple

from .logger import log

# 数据文件相对于本模块的位置
_DATA_FILE: str = os.path.join(os.path.dirname(__file__), "keywords_data.json")


def _load_raw() -> dict:
    """从 JSON 文件读取原始关键词数据（异常隔离）。"""
    log.debug("_load_raw 入口 | file=%s", _DATA_FILE)
    try:
        with open(_DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("JSON 顶层结构异常")
        log.debug("_load_raw 出口 | sections=%d", len(data))
        return data
    except Exception as exc:
        log.error("读取关键词数据文件失败: %s\n%s", _DATA_FILE, traceback.format_exc())
        raise


def _save_raw(data: dict) -> None:
    """将关键词数据写回 JSON 文件（异常隔离）。"""
    try:
        with open(_DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        log.error("写入关键词数据文件失败: %s\n%s", _DATA_FILE, traceback.format_exc())
        raise


def load_language_keywords() -> Dict[str, List[str]]:
    """从 JSON 加载语言范畴关键词。"""
    data = _load_raw()
    return data.get("language_keywords", {})


def load_type_keywords() -> List[Tuple[str, List[str]]]:
    """从 JSON 加载类型关键词（转为元组列表）。"""
    data = _load_raw()
    raw = data.get("type_keywords", [])
    return [(item[0], item[1]) for item in raw if len(item) >= 2]


def load_platform_keywords() -> Dict[str, List[str]]:
    """从 JSON 加载平台关键词。"""
    data = _load_raw()
    return data.get("platform_keywords", {})


def load_severity_keywords() -> Dict[str, List[str]]:
    """从 JSON 加载严重度关键词。"""
    data = _load_raw()
    return data.get("severity_keywords", {"高": [], "低": []})


def load_avoidance_headers() -> List[str]:
    """从 JSON 加载规避方法标题关键词。"""
    data = _load_raw()
    return data.get("avoidance_headers", [])


def reload() -> None:
    """热加载：从 JSON 重新读取全部关键词，更新 config 模块的全局变量。

    extractor 通过 config.LANGUAGE_KEYWORDS 等模块级变量访问关键词，
    reload() 直接修改这些变量的内容，下次抽取自动使用新关键词。
    无需重启 NiceGUI 服务。
    """
    # 延迟导入避免模块级循环依赖（仅在调用时导入 config）
    from . import config  # noqa: PLC0415

    try:
        data = _load_raw()
        config.LANGUAGE_KEYWORDS = data.get("language_keywords", {})
        raw_types = data.get("type_keywords", [])
        config.TYPE_KEYWORDS = [(item[0], item[1]) for item in raw_types if len(item) >= 2]
        config.PLATFORM_KEYWORDS = data.get("platform_keywords", {})
        config.SEVERITY_KEYWORDS = data.get("severity_keywords", {"高": [], "低": []})
        config.AVOIDANCE_HEADERS = data.get("avoidance_headers", [])
        log.info("关键词热加载成功，已从 %s 更新", _DATA_FILE)
    except Exception as exc:
        log.error("关键词热加载失败: %s\n%s", exc, traceback.format_exc())
        raise


def get_all_known_keywords() -> Set[str]:
    """返回当前已知的所有关键词（去重小写集合），供候选发现去重。

    Returns:
        Set[str]: 全部已知关键词的小写集合
    """
    from . import config  # noqa: PLC0415

    result: Set[str] = set()
    # 遍历所有关键词来源
    for kw_dict in [config.LANGUAGE_KEYWORDS, config.PLATFORM_KEYWORDS,
                    config.SEVERITY_KEYWORDS]:
        for kws in kw_dict.values():
            for kw in kws:
                result.add(kw.lower())
    for _label, kws in config.TYPE_KEYWORDS:
        for kw in kws:
            result.add(kw.lower())
    for kw in config.AVOIDANCE_HEADERS:
        result.add(kw.lower())
    return result


def add_keyword(section: str, category: str, keyword: str) -> bool:
    """向 JSON 文件添加新关键词，并同步更新内存。

    Args:
        section: 关键词分区（"language_keywords"｜"type_keywords"｜
                 "platform_keywords"｜"severity_keywords"｜"avoidance_headers"）
        category: 所属分类（如 "Python"｜"命令行"｜"Windows"；avoidance_headers 传 ""）
        keyword: 要添加的关键词

    Returns:
        bool: True 表示添加成功
    """
    try:
        data = _load_raw()
        # 按分区类型写入
        if section == "avoidance_headers":
            if keyword not in data.get(section, []):
                data.setdefault(section, []).append(keyword)
        elif section in ("language_keywords", "platform_keywords", "severity_keywords"):
            data.setdefault(section, {}).setdefault(category, [])
            if keyword not in data[section][category]:
                data[section][category].append(keyword)
        elif section == "type_keywords":
            items = data.get(section, [])
            for item in items:
                if item[0] == category:
                    if keyword not in item[1]:
                        item[1].append(keyword)
                    break
            else:
                # 分类不存在则新建
                items.append([category, [keyword]])
                data[section] = items
        else:
            log.warning("未知关键词分区: %s", section)
            return False

        _save_raw(data)
        # 立即同步到内存（reload 也可，但这里更精准）
        reload()
        log.info("关键词已添加: section=%s category=%s keyword=%s", section, category, keyword)
        return True
    except Exception as exc:
        log.error("添加关键词失败: %s\n%s", exc, traceback.format_exc())
        return False


def clear_category(section: str, category: str) -> int:
    """清空某个分类下的所有关键词（用于撤销批量添加）。"""
    try:
        data = _load_raw()
        if section not in data or category not in data.get(section, {}):
            return 0
        count = len(data[section][category])
        del data[section][category]
        _save_raw(data)
        reload()
        log.info("已清空分类: section=%s category=%s, 移除=%d个", section, category, count)
        return count
    except Exception as exc:
        log.error("清空分类失败: %s\n%s", exc, traceback.format_exc())
        return 0
