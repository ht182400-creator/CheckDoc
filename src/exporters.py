# encoding: utf-8
"""导出器（P1-2/P3）：CSV / Excel / Markdown / PDF。

设计：
- 纯函数：只接收表格行（dict 列表），返回 bytes，不依赖 NiceGUI 运行时，便于单测。
- 中文支持：PDF 走 reportlab 内置 CID 字体 STSong-Light（无需打包 TTF）渲染中文。
- CSV 带 BOM 便于 Excel 识别 UTF-8；_path 与质量分通过 EXTRA_EXPORT_FIELDS 附加。
"""
import csv
import io
from typing import Dict, List, Optional

from . import config
from .logger import log


def flatten(v) -> str:
    """列表/标量统一为可写入文本的字符串（与 UI 搜索共用同一语义）。"""
    if isinstance(v, list):
        return "; ".join(str(x) for x in v)
    return "" if v is None else str(v)


def build_csv(rows: List[Dict]) -> bytes:
    """构造 CSV 字节流（UTF-8 + BOM），列 = Schema 字段 + 附加字段。"""
    fieldnames = [f.key for f in config.SCHEMA] + config.EXTRA_EXPORT_FIELDS
    buf = io.StringIO()
    buf.write("﻿")  # BOM，Excel 识别 UTF-8
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        row = {f.key: flatten(r.get(f.key)) for f in config.SCHEMA}
        row["_path"] = r.get("_path", "")
        writer.writerow(row)
    return buf.getvalue().encode("utf-8")


def build_xlsx(rows: List[Dict]) -> bytes:
    """构造 Excel 字节流；未安装 openpyxl 时抛 RuntimeError（由上层回落 CSV）。"""
    try:
        import openpyxl  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError("no_openpyxl") from exc

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "MemoAlign"
    fieldnames = [f.key for f in config.SCHEMA] + config.EXTRA_EXPORT_FIELDS
    ws.append(fieldnames)
    for r in rows:
        row = [flatten(r.get(f.key)) for f in config.SCHEMA]
        row.append(r.get("_path", ""))
        ws.append(row)
    # 自适应列宽（上限 50 避免极宽）
    for col in ws.columns:
        max_len = max((len(str(cell.value or "")) for cell in col), default=10)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, 50)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_md(rows: List[Dict]) -> bytes:
    """按类型分组构造 Markdown 摘要字节流。"""
    groups: Dict[str, List[Dict]] = {}
    for r in rows:
        groups.setdefault(r.get("type", "其他"), []).append(r)
    lines = ["# MemoAlign 导出摘要", f"\n共 {len(rows)} 条记录，按类型分组：\n"]
    for typ, items in groups.items():
        lines.append(f"## {typ}（{len(items)}）")
        for r in items:
            lang = flatten(r.get("language"))
            av = flatten(r.get("avoidance"))
            q = r.get(config.QUALITY_SCORE_KEY)
            q_text = f" 质量分:{q}" if isinstance(q, int) else ""
            lines.append(f"- **{flatten(r.get('content'))}** 〔{lang}〕 {av}{q_text}")
        lines.append("")
    return "\n".join(lines).encode("utf-8")


def build_pdf(rows: List[Dict], title: str = "MemoAlign 导出") -> bytes:
    """构造 PDF 字节流（含中文，reportlab 内置 CID 字体 STSong-Light）。

    未安装 reportlab 时抛 RuntimeError（由上层提示 pip install reportlab）。
    布局：标题 + 按类型分组 + 每条记录的要点/元数据/规避方法。
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.colors import HexColor
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer,
        )
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    except ImportError as exc:
        raise RuntimeError("no_reportlab") from exc

    # STSong-Light 为 Adobe 亚洲 CID 字体，无需本地 TTF 即可渲染中文
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    FONT = "STSong-Light"

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, title=title,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
    )
    styles = getSampleStyleSheet()
    h_style = ParagraphStyle("h", parent=styles["Heading2"],
                             fontName=FONT, fontSize=14, spaceAfter=4)
    sub_style = ParagraphStyle("sub", parent=styles["Heading3"],
                               fontName=FONT, fontSize=11, spaceBefore=6, spaceAfter=2)
    body_style = ParagraphStyle("b", parent=styles["BodyText"],
                                fontName=FONT, fontSize=9, leading=13)
    meta_style = ParagraphStyle("m", parent=styles["BodyText"],
                                fontName=FONT, fontSize=8, leading=11,
                                textColor=HexColor("#555555"))

    story = []
    story.append(Paragraph(f"{title}（共 {len(rows)} 条）", h_style))
    story.append(Spacer(1, 6))

    groups: Dict[str, List[Dict]] = {}
    for r in rows:
        groups.setdefault(r.get("type", "其他"), []).append(r)
    for typ, items in groups.items():
        story.append(Paragraph(f"{typ}（{len(items)}）", sub_style))
        for r in items:
            content = flatten(r.get("content")) or "（无内容）"
            lang = flatten(r.get("language"))
            sev = flatten(r.get("severity"))
            av = flatten(r.get("avoidance"))
            q = r.get(config.QUALITY_SCORE_KEY)
            q_text = f"质量分:{q}" if isinstance(q, int) else "质量分:未评分"
            story.append(Paragraph(f"• {content}", body_style))
            story.append(Paragraph(
                f"语言：{lang} ｜ 严重度：{sev} ｜ 类型：{typ} ｜ {q_text}", meta_style))
            if av:
                story.append(Paragraph(f"规避：{av}", meta_style))
            story.append(Spacer(1, 4))

    doc.build(story)
    return buf.getvalue()
