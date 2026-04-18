from __future__ import annotations

import time
from typing import Any, Iterator, Literal

from importlib import import_module

OpenAI = Any  # type: ignore[assignment]
OpenAIError = Exception


def _load_openai() -> tuple[Any, type[Exception]]:
    module = import_module("openai")
    return module.OpenAI, module.OpenAIError

from app.core.config import get_settings

ModelRoute = Literal["reasoning", "analysis", "fast"]


class DeepSeekClient:
    def __init__(self) -> None:
        settings = get_settings()
        openai_client, openai_error = _load_openai()
        global OpenAI, OpenAIError
        OpenAI = openai_client
        OpenAIError = openai_error
        self._client = OpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            timeout=settings.request_timeout,
        )
        self._reasoning_model = settings.deepseek_reasoning_model
        self._fast_model = settings.deepseek_fast_model
        self._fallback_model = settings.doubao_model
        self._max_retries = settings.max_retries

    def route_model(self, task_type: str) -> str:
        normalized = task_type.lower().strip()
        if normalized in {"reasoning", "risk", "impact", "analysis", "critical"}:
            return self._reasoning_model
        if normalized in {"parse", "summary", "extract", "draft", "fast"}:
            return self._fallback_model or self._fast_model
        return self._fast_model

    def chat(
        self,
        prompt: str,
        *,
        system_prompt: str = "你是一个专业的合同审核助手。",
        temperature: float = 0.2,
        task_type: str = "analysis",
    ) -> str:
        response = self.chat_completion(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            stream=False,
            temperature=temperature,
            task_type=task_type,
        )
        return response.choices[0].message.content or ""

    def chat_completion(
        self,
        messages: list[dict[str, Any]],
        *,
        stream: bool = False,
        temperature: float = 0.2,
        task_type: str = "analysis",
        **kwargs: Any,
    ) -> Any:
        model = self.route_model(task_type)
        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                return self._client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    stream=stream,
                    **kwargs,
                )
            except OpenAIError as exc:
                last_error = exc
                if attempt >= self._max_retries:
                    break
                time.sleep(min(2 ** (attempt - 1), 8))
        raise RuntimeError("DeepSeek request failed after retries") from last_error

    def stream_chat_completion(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.2,
        task_type: str = "analysis",
        **kwargs: Any,
    ) -> Iterator[str]:
        response = self.chat_completion(messages, stream=True, temperature=temperature, task_type=task_type, **kwargs)
        for chunk in response:
            delta = chunk.choices[0].delta
            content = getattr(delta, "content", None)
            if content:
                yield content
