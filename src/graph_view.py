# encoding: utf-8
"""图谱视图：基于 ECharts 的多维数据可视化。

设计理念：900+ 节点用 force-directed 网络图会糊成一片，
改用更适合"分类聚合"数据的 treemap + 堆叠柱状图。

提供两种模式：
- "treemap"（默认）：层级树图，按 语言→类型 聚合，size=数量。小方块自动合并。
- "bar"：堆叠柱状图，横轴=语言（Top6），堆叠=类型分布。
"""
from collections import Counter
from typing import Dict, List, Tuple

from .logger import log

# 类别配色
_LANG_COLOR: Dict[str, str] = {
    "Python": "#3776AB",
    "JavaScript/TS": "#F7DF1E",
    "Go": "#00ADD8",
    "Rust": "#DEA584",
    "Shell/Bash": "#4EAA25",
    "PowerShell": "#5391FE",
    "Batch/CMD": "#888888",
    "Docker": "#2496ED",
    "Git/GitHub": "#F05032",
    "通用（待分类）": "#9B59B6",
    "通用": "#95A5A6",
    "其他": "#BDC3C7",
}
_DEFAULT_COLOR: str = "#95A5A6"

_TYPE_COLOR: Dict[str, str] = {
    "问题": "#E74C3C",
    "陷阱": "#E67E22",
    "最佳实践": "#27AE60",
    "规范": "#16A085",
    "经验": "#2980B9",
    "发布": "#8E44AD",
    "环境配置": "#D35400",
    "命令行": "#1ABC9C",
    "兼容性": "#F39C12",
    "其他": "#7F8C8D",
}

# 视图参数
_MAX_BUCKETS: int = 200  # 节点上限


def _aggregate_by_lang_type(records: List[Dict]) -> List[Dict]:
    """按 (语言, 类型) 聚合记录。"""
    counter: Counter = Counter()
    for r in records:
        langs = r.get("language") or ["通用"]
        # 主分类：第一个语言（避免重复计数）
        primary_lang = langs[0] if langs else "通用"
        typ = r.get("type", "其他")
        counter[(primary_lang, typ)] += 1
    result = []
    for (lang, typ), count in counter.most_common(_MAX_BUCKETS):
        result.append({
            "name": f"{lang} / {typ}",
            "lang": lang,
            "type": typ,
            "value": count,
        })
    return result


def _aggregate_by_type(records: List[Dict]) -> List[Dict]:
    """按类型聚合（用于柱状图）。"""
    counter: Counter = Counter()
    for r in records:
        counter[r.get("type", "其他")] += 1
    return [{"name": k, "value": v, "itemStyle": {"color": _TYPE_COLOR.get(k, _DEFAULT_COLOR)}}
            for k, v in counter.most_common()]


def _aggregate_by_lang(records: List[Dict]) -> List[Dict]:
    """按语言聚合（用于柱状图）。"""
    counter: Counter = Counter()
    for r in records:
        langs = r.get("language") or ["通用"]
        for lg in langs:
            counter[lg] += 1
    return [{"name": k, "value": v, "itemStyle": {"color": _LANG_COLOR.get(k, _DEFAULT_COLOR)}}
            for k, v in counter.most_common()]


def _treemap_option(records: List[Dict]) -> dict:
    """Treemap 视图：语言 → 类型 分层聚合。小方块合并为\"其他\"。"""
    all_data = _aggregate_by_lang_type(records)
    if not all_data:
        return {"title": {"text": "无数据", "left": "center", "top": "center"}}

    total = sum(d["value"] for d in all_data)
    threshold_pct = 0.01  # 低于总量 1% 的合并
    threshold_abs = 5     # 或数量 ≤ 5

    top_data = []
    small_items = []
    for d in all_data:
        if d["value"] / total >= threshold_pct and d["value"] > threshold_abs:
            top_data.append(d)
        else:
            small_items.append(d)

    # 合并小项
    if small_items:
        small_total = sum(d["value"] for d in small_items)
        small_names = ", ".join(d["name"] for d in small_items[:10])
        if len(small_items) > 10:
            small_names += f" ... 等{len(small_items)}项"
        top_data.append({
            "name": f"其他（{len(small_items)}项）",
            "lang": "其他",
            "type": "其他",
            "value": small_total,
            "tooltip": {"formatter": f"<b>其他</b><br/>{small_names}<br/>合计: {small_total}"},
        })

    return {
        "title": {
            "text": f"知识层级图（{len(records)} 条 · {len(top_data)} 分类）",
            "left": "center",
            "textStyle": {"fontSize": 14, "fontWeight": "normal"},
        },
        "tooltip": {
            "trigger": "item",
            "formatter": "<b>{b}</b><br/>数量: {c}",
            "backgroundColor": "rgba(50,50,50,0.9)",
            "textStyle": {"color": "#fff"},
        },
        "series": [{
            "type": "treemap",
            "roam": True,
            "nodeClick": "link",
            "data": top_data,
            "width": "100%",
            "height": "80%",
            "label": {
                "show": True,
                "formatter": "{b|{b}}\n{c|{c} 条}",
                "rich": {
                    "b": {"fontSize": 11, "color": "#fff", "fontWeight": "bold"},
                    "c": {"fontSize": 10, "color": "#eee"},
                },
            },
            "itemStyle": {
                "borderColor": "#fff",
                "borderWidth": 2,
            },
            "levels": [{
                "itemStyle": {"gapWidth": 6, "borderRadius": 4},
                "upperLabel": {"show": True, "height": 28, "fontSize": 11, "color": "#fff"},
            }],
            "breadcrumb": {"show": False},
        }],
    }


def _treemap_lang_grouped_option(records: List[Dict]) -> dict:
    """分组 Treemap：每个语言一个独立的矩形区域，内部按类型着色。"""
    all_data = _aggregate_by_lang_type(records)
    if not all_data:
        return {"title": {"text": "无数据", "left": "center", "top": "center"}}

    # 按语言分组（只用 Top 6 语言，其余合并）
    lang_groups: Dict[str, List[Dict]] = {}
    for d in all_data:
        lang = d["lang"]
        lang_groups.setdefault(lang, []).append(d)

    # 合并小众语言
    top_langs = sorted(lang_groups.keys(), key=lambda k: -sum(d["value"] for d in lang_groups[k]))[:6]
    other_langs = [k for k in lang_groups.keys() if k not in top_langs]
    if other_langs:
        lang_groups["其他语言"] = sum((lang_groups[ol] for ol in other_langs), [])

    result_langs = top_langs + (["其他语言"] if other_langs else [])
    total_cols = min(len(result_langs), 3)
    total_rows = (len(result_langs) + total_cols - 1) // total_cols

    series = []
    for idx, lang in enumerate(result_langs):
        items = lang_groups[lang]
        lang_total = sum(d["value"] for d in items)
        col = idx % total_cols
        row = idx // total_cols
        cw = 100.0 / total_cols
        rh = 80.0 / total_rows
        series.append({
            "type": "treemap",
            "roam": False,
            "nodeClick": False,
            "data": [{"name": f"{d['type']}\n{d['value']}", "value": d["value"]} for d in items],
            "width": f"{cw}%",
            "height": f"{rh}%",
            "left": f"{col * cw}%",
            "top": f"{row * rh}%",
            "label": {"show": True, "formatter": "{b}", "fontSize": 10, "color": "#fff"},
            "itemStyle": {"borderColor": "#fff", "borderWidth": 2},
            "breadcrumb": {"show": False},
        })

    return {
        "title": {
            "text": f"分语言区域图（{len(records)} 条 · {len(all_data)} 分类）",
            "left": "center",
            "textStyle": {"fontSize": 14, "fontWeight": "normal"},
        },
        "tooltip": {"trigger": "item", "formatter": "<b>{b}</b><br/>数量: {c}"},
        "series": series,
    }


def _bar_option(records: List[Dict]) -> dict:
    """单图堆叠柱状图：横轴=语言，堆叠=类型分布。"""
    type_color = {"问题": "#E74C3C", "陷阱": "#E67E22", "最佳实践": "#27AE60",
                  "规范": "#16A085", "经验": "#2980B9", "发布": "#8E44AD",
                  "环境配置": "#D35400", "命令行": "#1ABC9C", "兼容性": "#F39C12",
                  "其他": "#7F8C8D"}
    # 按语言和类型聚合
    by_lang: Dict[str, Counter] = {}
    for r in records:
        langs = r.get("language") or ["通用"]
        typ = r.get("type", "其他")
        primary = langs[0] if langs else "通用"
        by_lang.setdefault(primary, Counter())[typ] += 1
    # 排序：按总记录数降序，取 Top 6 语言
    top_langs = sorted(by_lang.keys(), key=lambda k: -sum(by_lang[k].values()))[:6]
    all_types = sorted({t for c in by_lang.values() for t in c.keys()})
    # 构建堆叠 series
    series = []
    for typ in all_types:
        data = [by_lang[l].get(typ, 0) for l in top_langs]
        series.append({
            "name": typ, "type": "bar", "stack": "totals", "data": data,
            "itemStyle": {"color": type_color.get(typ, "#999")},
            "label": {"show": True, "position": "inside", "fontSize": 10, "formatter": "{c}"},
            "emphasis": {"focus": "series"},
        })
    return {
        "title": {"text": f"语言×类型 堆叠分布（{len(records)} 条）", "left": "center", "top": 5,
                   "textStyle": {"fontSize": 14, "fontWeight": "normal"}},
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
        "legend": {"data": all_types, "top": 35, "type": "plain", "textStyle": {"fontSize": 11}},
        "grid": {"left": "5%", "right": "5%", "top": 80, "bottom": 30, "containLabel": True},
        "xAxis": {"type": "category", "data": top_langs, "axisLabel": {"fontSize": 12}},
        "yAxis": {"type": "value", "name": "记录数"},
        "series": series,
    }


def _network_option(records: List[Dict]) -> dict:
    """网络图：仅当记录 ≤ 100 条时使用，否则提示。"""
    if len(records) > _MAX_BUCKETS:
        # 自动降级为 treemap
        return _treemap_option(records)
    # 按 (lang, type) 聚合节点
    data = _aggregate_by_lang_type(records)
    nodes = []
    for d in data:
        lang = d["lang"]
        nodes.append({
            "id": d["name"],
            "name": d["name"],
            "symbolSize": 10 + d["value"] * 3,
            "category": d["lang"],
            "itemStyle": {"color": _LANG_COLOR.get(lang, _DEFAULT_COLOR)},
            "label": {"show": True, "fontSize": 10},
            "value": d["value"],
        })
    # 边：相同语言的节点连成链
    links = []
    by_lang: Dict[str, List[str]] = {}
    for d in data:
        by_lang.setdefault(d["lang"], []).append(d["name"])
    for ids in by_lang.values():
        for i in range(len(ids) - 1):
            links.append({"source": ids[i], "target": ids[i + 1], "lineStyle": {"opacity": 0.4}})
    return {
        "title": {"text": f"网络图（{len(nodes)} 节点, {len(links)} 连线）", "left": "center", "textStyle": {"fontSize": 14}},
        "tooltip": {"formatter": "<b>{b}</b><br/>数量: {c}"},
        "legend": [{"data": list(by_lang.keys()), "type": "scroll", "top": 30}],
        "series": [{
            "type": "graph",
            "layout": "force",
            "data": nodes,
            "links": links,
            "categories": [{"name": k, "itemStyle": {"color": _LANG_COLOR.get(k, _DEFAULT_COLOR)}} for k in by_lang.keys()],
            "roam": True,
            "draggable": True,
            "force": {"repulsion": 200, "edgeLength": 60},
            "label": {"show": True, "position": "right", "fontSize": 10},
            "lineStyle": {"opacity": 0.4},
        }],
    }


def build_graph_option(records: List[Dict], mode: str = "treemap") -> dict:
    """根据 records 大小自动选择最佳视图。

    Args:
        records: 当前可见记录列表
        mode: 视图模式（"treemap" | "bar" | "network"），默认 "treemap"

    Returns:
        dict: ECharts option
    """
    if not records:
        return {"title": {"text": "无数据", "left": "center", "top": "center"}}
    try:
        if mode == "bar":
            return _bar_option(records)
        elif mode == "network":
            return _network_option(records)
        else:
            return _treemap_option(records)
    except Exception as exc:
        log.error("图谱构建异常: %s", exc)
        return {"title": {"text": f"图谱构建失败: {exc}", "left": "center", "top": "center"}}
