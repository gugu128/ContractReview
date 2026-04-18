"""DeepSeek API 调用封装。"""

from __future__ import annotations

import json
from typing import Any, Dict

import requests

from app.utils import get_deepseek_api_key


class DeepSeekClient:
    """负责调用 DeepSeek 官方接口。"""

    def __init__(self, api_key: str | None = None):
        self.api_key = (api_key or get_deepseek_api_key()).strip()
        self.base_url = "https://api.deepseek.com/chat/completions"

    def review_contract(self, prompt: str) -> Dict[str, Any]:
        """把提示词发给 DeepSeek，并尽量解析为 JSON。"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "deepseek-chat",
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是专业合同审查助手。必须严格遵守用户给出的输出格式要求，"
                        "只输出合法 JSON，不要输出任何解释、前后缀或 Markdown。"
                        "你必须逐条审查规则，不得选择性忽略明显违反的规则。"
                        "判断时只能依据合同原文与规则库中的触发条件/不触发条件/边界说明，不得凭经验脑补。"
                        "如果合同原文明确满足不触发条件，则不得输出该规则的风险项。"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        }

        resp = requests.post(self.base_url, headers=headers, json=payload, timeout=120)
        if resp.status_code != 200:
            raise RuntimeError(f"DeepSeek API 调用失败：{resp.status_code} - {resp.text}")

        data = resp.json()
        content = data["choices"][0]["message"]["content"].strip()
        return self._parse_json(content)

    def _parse_json(self, text: str) -> Dict[str, Any]:
        """尽量把模型返回内容解析成 JSON。"""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                return json.loads(text[start : end + 1])
            raise RuntimeError(f"模型返回内容不是有效 JSON：{text}")
