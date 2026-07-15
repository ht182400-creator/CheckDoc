# encoding: utf-8
"""图谱视图：ECharts 力导向聚类图（按语言/类型/平台聚类节点, 零额外依赖）。

通过 NiceGUI 的 `ui.echart` 渲染，传入原始 ECharts option dict 即可。
"""
from collections import Counter
from typing import Dict, List

from . import config
from .logger import log

# 类别颜色映射（按语言范畴配色）
_CATEGORY_COLORS: Dict[str, str] = {
    "Python": "#3776AB",
    "JavaScript/TS": "#F7DF1E",
    "Go": "#00ADD8",
    "Rust": "#DEA584",
    "Shell/Bash": "#4EAA25",
    "PowerShell": "#5391FE",
    "Batch/CMD": "#808080",
    "Docker": "#2496ED",
    "Git/GitHub": "#F05032",
    "通用": "#95A5A6",
    "其他": "#BDC3C7",
}
# 默认颜色
_DEFAULT_CAT_COLOR: str = "#95A5A6"
# 图谱参数
_NODE_SYMBOL_SIZE_MIN: int = 15     # 最小节点半径
_NODE_SYMBOL_SIZE_MAX: int = 60     # 最大节点半径
_FORCE_REPULSION: int = 300         # 力导向斥力


def build_graph_option(records: List[Dict]) -> dict:
    """从记录列表构建 ECharts 力导向图 option。

    节点 = 去重后的每条记录（size 按严重度差异化），
    链接 = 共享标签的记录之间连线。

    Args:
        records: 当前可见记录列表

    Returns:
        dict: ECharts option（可直接传入 ui.echart）
    """
    if not records:
        return {
            "title": {"text": "无数据", "left": "center", "top": "center"},
        }

    try:
        # 1) 统计类别（语言范畴）及其频次
        cat_counter: Counter = Counter()
        for r in records:
            for lg in (r.get("language") or []):
                cat_counter[lg] += 1
        if not cat_counter:
            cat_counter["通用"] = 1

        # 取 Top 10 语言作为 categories
        top_langs = [lang for lang, _ in cat_counter.most_common(10)]
        categories = [
            {"name": lang, "itemStyle": {"color": _CATEGORY_COLORS.get(lang, _DEFAULT_CAT_COLOR)}}
            for lang in top_langs
        ]
        lang_index = {lang: i for i, lang in enumerate(top_langs)}

        # 2) 构建节点（去重记录）
        nodes = []
        for i, r in enumerate(records):
            # 严重度 → 节点大小
            sev_map = {"高": 50, "中": 30, "低": 18}
            symbol_size = sev_map.get(r.get("severity", "中"), 30)
            # 取首个匹配的语言作为分类
            r_langs = r.get("language") or []
            cat_idx = lang_index.get(r_langs[0], len(categories) - 1) if r_langs else 0
            # 节点标签（截断过长的标题）
            content = r.get("content", "")[:20]
            nodes.append({
                "id": str(i),
                "name": content,
                "symbolSize": symbol_size,
                "category": cat_idx,
                "label": {"show": symbol_size > 25, "fontSize": 10},
                "tooltip": {"formatter": f"{content}<br/>类型:{r.get('type','')} | 严重度:{r.get('severity','')}"},
            })

        # 3) 构建链接（共享标签≥1即连线）
        links = []
        # 按标签分组（词 → 节点索引列表）
        tag_nodes: Dict[str, List[int]] = {}
        for i, r in enumerate(records):
            for tag in (r.get("tags") or []):
                tag_nodes.setdefault(str(tag), []).append(i)

        link_set = set()
        for indices in tag_nodes.values():
            if len(indices) < 2:
                continue
            for a in range(len(indices)):
                for b in range(a + 1, len(indices)):
                    pair = (min(indices[a], indices[b]), max(indices[a], indices[b]))
                    if pair not in link_set:
                        link_set.add(pair)
                        links.append({"source": str(pair[0]), "target": str(pair[1])})

        # 限制链接数（防止图谱过于密集）
        if len(links) > 500:
            links = links[:500]

        return {
            "title": {
                "text": f"知识图谱（{len(nodes)} 节点, {len(links)} 连线）",
                "left": "center",
                "textStyle": {"fontSize": 14},
            },
            "tooltip": {},
            "legend": [{"data": [c["name"] for c in categories]}],
            "series": [{
                "type": "graph",
                "layout": "force",
                "animation": True,
                "data": nodes,
                "links": links,
                "categories": categories,
                "roam": True,
                "draggable": True,
                "force": {
                    "repulsion": _FORCE_REPULSION,
                    "edgeLength": [80, 200],
                },
                "label": {"show": True, "position": "right", "fontSize": 10},
                "lineStyle": {"color": "source", "curveness": 0.3, "opacity": 0.3},
                "emphasis": {"focus": "adjacency", "lineStyle": {"width": 2}},
            }],
        }
    except Exception as exc:
        log.error("图谱构建异常: %s", exc)
        return {"title": {"text": f"图谱构建失败: {exc}", "left": "center", "top": "center"}}
