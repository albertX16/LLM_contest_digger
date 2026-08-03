from __future__ import annotations

import pytest

from automation.agents.llm_client import LLMClient


def test_deepseek_request_explicitly_controls_thinking(monkeypatch, tmp_path) -> None:
    key = tmp_path / "key.txt"
    key.write_text("test-key", encoding="utf-8")
    captured = {}

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {"choices": [{
                "finish_reason": "stop",
                "message": {"content": '{"ok": true}', "reasoning_content": "r"},
            }]}

    def fake_post(url, json, headers, timeout):
        captured.update(json)
        return Response()

    monkeypatch.setattr("automation.agents.llm_client.requests.post", fake_post)
    client = LLMClient(key, thinking=True, reasoning_effort="high")
    assert client.chat_json([{"role": "user", "content": "json"}]) == {"ok": True}
    assert captured["thinking"] == {"type": "enabled"}
    assert captured["reasoning_effort"] == "high"
    assert "max_tokens" not in captured
    assert "temperature" not in captured
    assert captured["response_format"] == {"type": "json_object"}


def test_empty_reasoning_only_response_retries_with_json_finalization(
    monkeypatch, tmp_path,
) -> None:
    key = tmp_path / "key.txt"
    key.write_text("test-key", encoding="utf-8")
    payloads = []

    class Response:
        status_code = 200

        def __init__(self, content):
            self.content = content

        def json(self):
            return {"choices": [{
                "finish_reason": "stop",
                "message": {
                    "content": self.content,
                    "reasoning_content": "reasoning",
                },
            }]}

    def fake_post(url, json, headers, timeout):
        payloads.append(json)
        return Response("" if len(payloads) == 1 else '{"ok": true}')

    monkeypatch.setattr("automation.agents.llm_client.requests.post", fake_post)
    client = LLMClient(key, thinking=True, retries=2)
    result = client.chat_json([{"role": "user", "content": "return json"}])

    assert result == {"ok": True}
    assert len(payloads) == 2
    assert payloads[0]["response_format"] == {"type": "json_object"}
    assert "previous API response" in payloads[1]["messages"][-1]["content"]


def test_empty_content_retry_never_escalates_max_tokens(monkeypatch, tmp_path) -> None:
    key = tmp_path / "key.txt"
    key.write_text("test-key", encoding="utf-8")
    payloads = []

    class Response:
        status_code = 200

        def __init__(self, content):
            self.content = content

        def json(self):
            return {"choices": [{
                "finish_reason": "stop",
                "message": {"content": self.content, "reasoning_content": "r"},
            }]}

    def fake_post(url, json, headers, timeout):
        payloads.append(json)
        return Response("" if len(payloads) <= 2 else '{"ok": true}')

    monkeypatch.setattr("automation.agents.llm_client.requests.post", fake_post)
    client = LLMClient(key, thinking=True, retries=4)
    assert client.chat_json([{"role": "user", "content": "json"}]) == {"ok": True}
    for payload in payloads:
        assert "max_tokens" not in payload  # 输出永不设限
    assert "unlimited output budget" in payloads[1]["messages"][-1]["content"]


def test_preflight_ok(monkeypatch, tmp_path) -> None:
    key = tmp_path / "key.txt"
    key.write_text("test-key", encoding="utf-8")

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {"data": [{"id": "deepseek-v4-flash"}, {"id": "deepseek-v4-pro"}]}

    monkeypatch.setattr(
        "automation.agents.llm_client.requests.get",
        lambda *args, **kwargs: Response(),
    )
    client = LLMClient(key, model="deepseek-v4-flash")
    result = client.preflight()
    assert result["status"] == "ok"
    assert result["model"] == "deepseek-v4-flash"


def test_preflight_dns_failure_gives_actionable_error(monkeypatch, tmp_path) -> None:
    key = tmp_path / "key.txt"
    key.write_text("test-key", encoding="utf-8")

    def fail(*args, **kwargs):
        raise requests_exc

    import requests

    requests_exc = requests.ConnectionError("name resolution failed")
    monkeypatch.setattr("automation.agents.llm_client.requests.get", fail)
    client = LLMClient(key)
    with pytest.raises(RuntimeError, match="外网访问权限"):
        client.preflight()


def test_preflight_401_and_missing_model(monkeypatch, tmp_path) -> None:
    key = tmp_path / "key.txt"
    key.write_text("bad-key", encoding="utf-8")

    class Response401:
        status_code = 401

    monkeypatch.setattr(
        "automation.agents.llm_client.requests.get",
        lambda *args, **kwargs: Response401(),
    )
    with pytest.raises(RuntimeError, match="鉴权失败"):
        LLMClient(key).preflight()

    class Response200:
        status_code = 200

        @staticmethod
        def json():
            return {"data": [{"id": "other-model"}]}

    monkeypatch.setattr(
        "automation.agents.llm_client.requests.get",
        lambda *args, **kwargs: Response200(),
    )
    with pytest.raises(RuntimeError, match="不在可用列表"):
        LLMClient(key, model="deepseek-v4-flash").preflight()
