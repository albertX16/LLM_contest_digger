"""DeepSeek 官方 API 直连客户端。

两个 agent（planner/summarizer）都通过本模块调用 DeepSeek。自动化程序
内部直接使用 API key，不经过任何桥接服务。本模块只依赖标准库 + requests。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import requests


class LLMClient:
    """DeepSeek Chat Completions 客户端，带重试与超时。"""

    def __init__(
        self,
        key_file: str | Path,
        model: str = "deepseek-v4-flash",
        base_url: str = "https://api.deepseek.com",
        temperature: float = 0.8,
        max_tokens: int | None = None,
        timeout_s: float = 180,
        retries: int = 3,
        thinking: bool = True,
        reasoning_effort: str = "high",
    ) -> None:
        self.key_file = str(key_file)
        self.key = Path(key_file).read_text().strip()
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout_s = timeout_s
        self.retries = retries
        self.thinking = bool(thinking)
        if reasoning_effort not in {"high", "max"}:
            raise ValueError("DeepSeek reasoning_effort 必须是 high 或 max")
        self.reasoning_effort = reasoning_effort

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict[str, str] | None = None,
    ) -> str:
        """发送一轮对话，返回 assistant 文本内容；瞬时错误重试耗尽后抛出。"""
        max_tokens = self.max_tokens if max_tokens is None else max_tokens
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "thinking": {"type": "enabled" if self.thinking else "disabled"},
        }
        # DeepSeek V4 thinking mode explicitly ignores temperature/top_p.
        # Omitting unsupported controls makes the request contract unambiguous.
        if not self.thinking:
            payload["temperature"] = (
                self.temperature if temperature is None else temperature)
        if max_tokens is not None:
            payload["max_tokens"] = int(max_tokens)
        if response_format is not None:
            payload["response_format"] = response_format
        if self.thinking:
            payload["reasoning_effort"] = self.reasoning_effort
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
        }

        last_err: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                resp = requests.post(url, json=payload, headers=headers, timeout=self.timeout_s)
                if resp.status_code == 200:
                    data = resp.json()
                    choice = data["choices"][0]
                    message = choice["message"]
                    content = message.get("content") or ""
                    if content.strip():
                        return content
                    # DeepSeek JSON mode 偶发 reasoning_content 非空但 final content
                    # 为空。严格保持同一模型、thinking 和 JSON mode 原样重试；
                    # 不切模型、不关思考，也不生成程序化后备答案。
                    if attempt == self.retries:
                        raise RuntimeError(
                            "DeepSeek 返回空 content（客户端未限制 max_tokens；"
                            f"finish_reason={choice.get('finish_reason')}, "
                            f"reasoning_chars={len(message.get('reasoning_content') or '')}）"
                        )
                    last_err = RuntimeError(
                        "empty content, retrying the same strict JSON contract")
                    if response_format == {"type": "json_object"}:
                        payload["messages"] = [
                            *messages,
                            {"role": "user", "content": (
                                "The previous API response contained reasoning but no final "
                                "content. Return the required complete JSON object now. "
                                "Example shape (fill in every required field from the "
                                "schema above): "
                                '{"key_1": "value", "nested": {"a": 1}, "list": [1, 2]} '
                                "The first output character must be { and the last must be }. "
                                "Do not return prose, Markdown, or an empty response. "
                                "You have unlimited output budget; finish with content."
                            )},
                        ]
                    continue
                # 429/5xx 可重试；4xx 其它错误直接抛
                if resp.status_code in (429, 500, 502, 503, 504):
                    last_err = RuntimeError(f"DeepSeek HTTP {resp.status_code}: {resp.text[:300]}")
                    time.sleep(min(2**attempt, 30))
                    continue
                resp.raise_for_status()
            except requests.RequestException as exc:
                last_err = exc
                time.sleep(min(2**attempt, 30))

        raise RuntimeError(f"DeepSeek 请求失败（{self.retries} 次重试后）: {last_err}")

    def preflight(self, timeout_s: float = 15.0) -> dict:
        """启动前连通性/鉴权自检（只读，不消耗生成额度）。

        解决"沙箱阻止 api.deepseek.com / DNS 解析失败导致启动即失败"：
        在加载数据和启动研究前先验证网络与 key，失败时给出可操作提示
        （需要联网权限运行，例如外部 macOS Terminal 或网络放行）。
        """
        url = f"{self.base_url}/models"
        headers = {
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
        }
        try:
            resp = requests.get(url, headers=headers, timeout=timeout_s)
        except requests.RequestException as exc:
            raise RuntimeError(
                "DeepSeek 网络自检失败（无法连接 api.deepseek.com）："
                f"{exc}\n请确认运行环境具备外网访问权限（外部 Terminal / 网络放行），"
                "再重新启动。这不是研究逻辑错误，不会降级。"
            ) from exc
        if resp.status_code == 401:
            raise RuntimeError(
                f"DeepSeek key 鉴权失败 (HTTP 401)：检查 {self.key_file} 内容")
        if resp.status_code != 200:
            raise RuntimeError(f"DeepSeek /models 返回 HTTP {resp.status_code}")
        data = resp.json()
        models = [item.get("id") for item in data.get("data", [])]
        if self.model not in models:
            raise RuntimeError(
                f"配置模型 {self.model!r} 不在可用列表: {models[:20]}")
        return {"status": "ok", "model": self.model, "available_models": models}

    def chat_json(self, messages: list[dict[str, str]], **kw) -> dict[str, Any]:
        """请求模型返回严格 JSON 对象（允许标准 Markdown JSON 围栏）。"""
        text = self.chat(
            messages,
            response_format={"type": "json_object"},
            **kw,
        )
        # 模型偶尔会用 ```json 围栏包住结果
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValueError("DeepSeek 输出不是合法 JSON，严格模式中止") from exc


def load_config(config: dict) -> LLMClient:
    """从 default.yaml 的 llm 节构建客户端。"""
    llm = config["llm"]
    return LLMClient(
        key_file=llm["key_file"],
        model=llm["model"],
        base_url=llm.get("base_url", "https://api.deepseek.com"),
        temperature=llm.get("temperature", 0.8),
        max_tokens=llm.get("max_tokens", 4096),
        timeout_s=llm.get("timeout_s", 180),
        retries=llm.get("retries", 3),
        thinking=llm.get("thinking", True),
        reasoning_effort=("max" if llm.get("reasoning") in {"xhigh", "max"}
                          else "high"),
    )
