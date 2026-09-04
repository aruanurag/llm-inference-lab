import json

from app.benchmark import percentile, post_streaming_request


def test_percentile_handles_empty_values() -> None:
    assert percentile([], 95) is None


def test_percentile_returns_expected_value_for_small_set() -> None:
    assert percentile([1, 2, 3, 4, 5], 50) == 3
    assert percentile([1, 2, 3, 4, 5], 95) == 5


class _StreamingResponse:
    def __enter__(self):
        return [b'data: {"choices": [{"delta": {"content": "ok"}}]}\n', b'data: [DONE]\n']

    def __exit__(self, exc_type, exc, traceback):
        return False


def test_streaming_request_can_explicitly_disable_llama_prompt_cache(monkeypatch) -> None:
    payloads: list[dict] = []

    def fake_urlopen(request, timeout):
        payloads.append(json.loads(request.data.decode("utf-8")))
        return _StreamingResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = post_streaming_request(
        url="http://example.test/v1/chat/completions",
        prompt="A unique prefill prompt",
        prompt_index=0,
        request_id=1,
        max_tokens=8,
        temperature=0,
        cache_prompt=False,
    )

    assert result.status == "ok"
    assert payloads == [{
        "model": "local-model",
        "messages": [{"role": "user", "content": "A unique prefill prompt"}],
        "stream": True,
        "max_tokens": 8,
        "temperature": 0,
        "cache_prompt": False,
    }]
