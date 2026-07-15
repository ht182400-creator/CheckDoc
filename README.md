# MemoAlign · 记忆对齐分析器

将分散在 `**/memory/*.md` 中的知识笔记，对齐（归一化）为统一结构化表格，支持**表头排序、多列筛选、行下钻详情、CSV/Markdown 导出**。本地优先、零云依赖、Schema 驱动可扩展。

## 快速开始

```powershell
cd d:\Work_Area\Python\checkdoc
python -m venv .venv && .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m src.main
```

浏览器打开提示地址（默认 http://127.0.0.1:8080），输入根目录（默认 `D:\Work_Area\AI`）→ 点击「扫描」。

## 能力一览

- 递归扫描 `**/memory/*.md`
- 规则抽取（离线可用）+ 可选 LLM 抽取（OpenAI 兼容，可插拔）
- 交互表格：点击表头排序、按列文本/枚举筛选
- 行下钻：查看原文 Markdown 与元数据
- 增量缓存加速重扫；毫秒级日志 + 每日轮转

## 文档

见 [`docs/`](docs/README.md)：需求、架构、数据模型、接口、UI、测试、部署。

## 扩展

新增字段只需在 `src/config.py` 的 `SCHEMA` 追加一行 `FieldDef`，UI 自动出现新列与筛选器。
