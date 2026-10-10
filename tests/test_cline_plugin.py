"""Tests for the Cline plugin.

Needs the COVAS:NEXT source for lib.*: set COVAS_SRC to its src folder, or
check COVAS:NEXT out next to this repo (../Elite-Dangerous-AI-Integration).
"""

import importlib.util
import json
import os
from pathlib import Path
import sys

import httpx
import pytest
from openai import DefaultHttpxClient, OpenAI

ROOT = Path(__file__).resolve().parents[1]
COVAS_SRC = Path(os.environ.get("COVAS_SRC", ROOT.parent / "Elite-Dangerous-AI-Integration" / "src"))
sys.path.insert(0, str(COVAS_SRC))

from lib.Models import LLMError, OpenAILLMModel  # noqa: E402
from lib.PluginBase import PluginManifest  # noqa: E402
from lib.PluginManager import PluginManager  # noqa: E402

_spec = importlib.util.spec_from_file_location("cn_plugin_cline", ROOT / "cn-plugin-cline.py")
cline = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cline)

MANIFEST = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))

COMPLETION = {
    "id": "gen-123",
    "object": "chat.completion",
    "created": 1791585201,
    "model": "cline-pass/glm-5.3",
    "system_fingerprint": None,
    "choices": [{
        "finish_reason": "stop",
        "index": 0,
        "logprobs": None,
        "message": {"role": "assistant", "content": "Systems powering down. Docked and secure."},
    }],
    "usage": {"prompt_tokens": 12, "completion_tokens": 7, "total_tokens": 19},
}


def plugin():
    return cline.ClinePlugin(PluginManifest(json.dumps(MANIFEST)))


def with_transport(model, handler):
    model.client = OpenAI(
        base_url=cline.CLINE_API_URL, api_key="test-key", max_retries=0,
        http_client=DefaultHttpxClient(transport=cline.ClineEnvelopeTransport(httpx.MockTransport(handler))),
    )
    return model


def returning(status, body):
    return lambda request: httpx.Response(status, json=body)


def llm(**settings):
    return plugin().create_model("llm", {"api_key": "test-key", **settings})


# ── Envelope handling ────────────────────────────────────────────────────────


def test_wrapped_completion_is_unwrapped_and_parsed():
    model = with_transport(llm(), returning(200, {"success": True, "data": COMPLETION}))
    text, _, usage = model.generate([{"role": "user", "content": "status"}])
    assert text == "Systems powering down. Docked and secure."
    assert usage.total_tokens == 19
    assert usage.provider == "cline"


def test_unwrapped_completion_still_works():
    model = with_transport(llm(), returning(200, COMPLETION))
    text, _, _ = model.generate([{"role": "user", "content": "status"}])
    assert text == "Systems powering down. Docked and secure."


def test_tool_calls_survive_unwrapping():
    completion = json.loads(json.dumps(COMPLETION))
    completion["choices"][0]["message"] = {
        "role": "assistant", "content": None,
        "tool_calls": [{"id": "call_1", "type": "function",
                        "function": {"name": "fireWeapons", "arguments": "{}"}}],
    }
    model = with_transport(llm(), returning(200, {"success": True, "data": completion}))
    _, actions, _ = model.generate([{"role": "user", "content": "fire"}])
    assert actions is not None and actions[0].function.name == "fireWeapons"


def test_success_false_on_200_raises_instead_of_empty_reply():
    model = with_transport(llm(), returning(200, {"success": False, "error": "Insufficient credits"}))
    with pytest.raises(LLMError, match="Insufficient credits"):
        model.generate([{"role": "user", "content": "status"}])


def test_wrapped_http_error_message_is_surfaced():
    # Cline answers model failures as a 500 with the same envelope
    model = with_transport(llm(), returning(500, {"success": False, "error": "empty response content"}))
    with pytest.raises(LLMError, match="empty response content"):
        model.generate([{"role": "user", "content": "status"}])


def test_non_envelope_json_passes_through_untouched():
    transport = cline.ClineEnvelopeTransport(httpx.MockTransport(returning(200, {"data": [1, 2, 3]})))
    with httpx.Client(transport=transport) as client:
        assert client.get("https://api.cline.bot/api/v1/models").json() == {"data": [1, 2, 3]}


# ── Providers ────────────────────────────────────────────────────────────────


def test_llm_and_agent_slots_are_independent():
    providers = {p["id"]: p for p in plugin().model_providers or []}
    assert providers["llm"]["slots"] == ["llm"]
    assert providers["agent-llm"]["slots"] == ["agent_llm"]
    agent = plugin().create_model("agent-llm", {"agent_llm_model": "agent-model"})
    assert isinstance(agent, OpenAILLMModel)
    assert agent.model_name == "agent-model"
    assert str(agent.client.base_url) == cline.CLINE_API_URL


def test_tool_toggle_suppresses_tools():
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"success": True, "data": COMPLETION})

    model = with_transport(llm(llm_tools_enabled=False), handler)
    model.generate([{"role": "user", "content": "hi"}], [{"type": "function", "function": {"name": "t", "parameters": {"type": "object"}}}], "auto")
    assert "tools" not in sent[0]


def test_vision_slot_defaults_to_an_image_capable_model():
    providers = {p["id"]: p for p in plugin().model_providers or []}
    assert providers["vlm"]["kind"] == "vlm"
    assert providers["vlm"]["slots"] == ["vision"]
    vlm = plugin().create_model("vlm", {"api_key": "test-key"})
    assert vlm.model_name == cline.CLINE_VLM_MODEL != cline.CLINE_MODEL
    assert vlm.tools_enabled is False


def test_vision_request_sends_image_and_unwraps_reply():
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        reply = json.loads(json.dumps(COMPLETION))
        reply["choices"][0]["message"]["content"] = "A docking bay, pad 12 lit."
        return httpx.Response(200, json={"success": True, "data": reply})

    model = with_transport(plugin().create_model("vlm", {"api_key": "test-key"}), handler)
    image = {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}}
    text, _, _ = model.generate([{"role": "user", "content": [{"type": "text", "text": "what is this?"}, image]}])
    assert text == "A docking bay, pad 12 lit."
    assert sent[0]["model"] == cline.CLINE_VLM_MODEL
    assert image in sent[0]["messages"][0]["content"]


def test_no_embedding_provider():
    # Cline's /api/v1/embeddings returns 404
    assert not any(p["kind"] == "embedding" for p in plugin().model_providers or [])


# ── Loading as COVAS:NEXT does ───────────────────────────────────────────────


def test_loads_from_a_plugins_folder_like_covas(tmp_path, monkeypatch):
    """Copy the plugin into a plugins/ folder and load it the way COVAS:NEXT
    does at startup (folder name as package, manifest entrypoint)."""
    plugins_dir = tmp_path / "plugins"
    target = plugins_dir / "cn-plugin-cline"
    target.mkdir(parents=True)
    for name in ("cn-plugin-cline.py", "manifest.json", "__init__.py"):
        (target / name).write_bytes((ROOT / name).read_bytes())

    monkeypatch.chdir(tmp_path)
    manager = PluginManager({"plugin_settings": {MANIFEST["guid"]: {"api_key": "test-key"}}})  # type: ignore[arg-type]
    manager.load_plugins()
    manager.register_settings()

    assert not manager.failed_plugins, manager.failed_plugins
    model = manager.create_plugin_model(MANIFEST["guid"], "llm", "llm")
    assert type(model).__name__ == "ClineLLMModel"
