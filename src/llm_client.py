# encoding: utf-8
"""LLM 抽取适配（OpenAI 兼容协议，可选、可插拔）。

仅当 config.LLM_ENABLED=True 且配置了密钥时启用；失败抛异常，
由 extractor 自动回落到规则抽取，保证整体稳定。
"""
import json
import os
import urllib.request

from . import config
from .logger import log


def _strip_code_fence(text: str) -> str:
    """去除 LLM 可能返回的 ```json 代码围栏，提取纯 JSON。"""
    text = text.strip()
    if text.startswith("```"):
        # 去掉首行围栏与末尾围栏
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip()


class LLMExtractor:
    """OpenAI 兼容的 JSON 抽取器。"""

    def extract(self, text: str, schema) -> dict:
        """调用 LLM 按 Schema 抽取结构化记录。

        Args:
            text: 文件全文
            schema: config.SCHEMA 字段定义列表

        Returns:
            dict: 字段 key -> 值

        Raises:
            RuntimeError: 未配置密钥或请求失败
        """
        api_key = config.LLM_API_KEY or os.environ.get("MEMOALIGN_LLM_API_KEY", "")
        if not api_key:
            raise RuntimeError("未配置 LLM_API_KEY（或环境变量 MEMOALIGN_LLM_API_KEY）")

        schema_desc = "\n".join(
            f"- {f.key} ({f.label}, {f.ftype}): "
            + (f"候选值={','.join(f.options)}" if f.options else "自由文本")
            for f in schema
        )
        system = (
            "你是结构化信息抽取助手。请严格按给定 Schema 将用户提供的 Markdown 笔记"
            "抽取为 JSON 对象，键名必须与 Schema 字段 key 完全一致；"
            "multi/select 类型的值为数组或单值字符串；不要输出多余说明，只输出 JSON。"
        )
        user = f"Schema:\n{schema_desc}\n\n笔记正文:\n{text[:config.READ_CHUNK_LIMIT]}"

        payload = {
            "model": config.LLM_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
        }
        url = f"{config.LLM_BASE_URL.rstrip('/')}/chat/completions"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=config.LLM_TIMEOUT_SEC) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"]
            return json.loads(_strip_code_fence(content))
        except Exception as exc:
            log.warning("LLM 抽取失败，将回落规则抽取: %s", exc)
            raise
