"""Tests for the LLMClient transport port's real adapter.

``FakeLLMClient`` is exercised in test_resolver_offline.py. Here we verify
the production adapter ``UniInferLLMClient`` actually transports correctly:
request URL/key, ``verify=False`` (self-signed proxy cert), payload shape,
``think`` serialized as a JSON bool (not a string), content parsing, and the
error contract (returns \"\" instead of raising).
"""

import json
from unittest import mock

import llm_client as L


def _fake_response(status_code=200, payload=None):
    resp = mock.Mock()
    resp.status_code = status_code
    resp.json.return_value = payload if payload is not None else {
        "choices": [{"message": {"content": "Anna De Ville"}}]
    }
    return resp


def test_uniinfer_parses_content_and_sends_think_as_bool():
    with mock.patch.object(L.requests, "post", return_value=_fake_response()) as post:
        client = L.UniInferLLMClient(model="opencode@deepseek-v4-flash-free")
        out = client.complete(
            [{"role": "user", "content": "Anna De Ville solo"}],
            max_tokens=16, think=False,
        )
    assert out == "Anna De Ville"
    assert post.called
    args, kwargs = post.call_args
    assert args[0] == L.DEFAULT_API_URL
    assert kwargs["verify"] is False  # self-signed nginx proxy cert
    assert kwargs["headers"]["Authorization"] == f"Bearer {L.DEFAULT_API_KEY}"
    body = json.loads(kwargs["data"].decode())
    assert body["model"] == "opencode@deepseek-v4-flash-free"
    assert body["messages"] == [{"role": "user", "content": "Anna De Ville solo"}]
    assert body["max_tokens"] == 16
    assert body["think"] is False  # JSON bool, NOT the string "false"


def test_uniinfer_returns_empty_on_transport_error():
    bad = mock.Mock()
    bad.status_code = 500
    bad.json.side_effect = ValueError("not json")
    with mock.patch.object(L.requests, "post", return_value=bad):
        client = L.UniInferLLMClient()
        out = client.complete([{"role": "user", "content": "x"}], think=False)
    # Contract: never raises; returns "" on transport failure.
    assert out == ""
