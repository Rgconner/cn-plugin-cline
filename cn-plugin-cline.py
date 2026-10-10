"""Cline LLM and vision provider for COVAS:NEXT.

Cline's API (https://api.cline.bot/api/v1) is OpenAI-compatible except that
it wraps every response in an envelope:

    {"success": true, "data": {<OpenAI chat.completion>}}
    {"success": false, "error": "<message>"}

The OpenAI SDK parses the wrapped form into a ChatCompletion with every
field None, so COVAS reads each reply as empty.  This plugin gives the model
an httpx transport that unwraps the envelope before the SDK sees it.

Cline has no embeddings endpoint (/api/v1/embeddings returns 404), so only
LLM, agent LLM and vision providers are offered.
"""

import json
from typing import Any, List, Optional, override

import httpx
from openai import DefaultHttpxClient, OpenAI

from lib.Models import OpenAILLMModel
from lib.PluginBase import PluginBase, PluginManifest


CLINE_API_URL = "https://api.cline.bot/api/v1/"
CLINE_MODEL = "cline-pass/glm-5.3"
# Must accept image input: cline-pass/glm-5.3 is text-only and Cline drops
# the image silently (the model answers that it sees no image).
CLINE_VLM_MODEL = "google/gemini-3.8-flash"

REASONING_EFFORTS = ["default", "none", "minimal", "low", "medium", "high"]


# ── Settings fields ──────────────────────────────────────────────────────────
# Same shapes as COVAS's bundled provider plugins use; kept local so the
# plugin only depends on lib.PluginBase and lib.Models.


def text_field(key: str, label: str, default_value: str, *, hidden: bool = False) -> dict[str, Any]:
    return {
        "key": key, "label": label, "type": "text", "readonly": False,
        "placeholder": None, "default_value": default_value,
        "max_length": None, "min_length": None, "hidden": hidden,
    }


def number_field(key: str, label: str, default_value: float,
                 minimum: float, maximum: float, step: float) -> dict[str, Any]:
    return {
        "key": key, "label": label, "type": "number", "readonly": False,
        "placeholder": None, "default_value": default_value,
        "min_value": minimum, "max_value": maximum, "step": step,
    }


def toggle_field(key: str, label: str, default_value: bool) -> dict[str, Any]:
    return {
        "key": key, "label": label, "type": "toggle", "readonly": False,
        "placeholder": None, "default_value": default_value,
    }


def select_field(key: str, label: str, default_value: str, options: list[str]) -> dict[str, Any]:
    return {
        "key": key, "label": label, "type": "select", "readonly": False,
        "placeholder": None, "default_value": default_value,
        "select_options": [
            {"key": o, "label": o.replace("_", " ").title(), "value": o, "disabled": False}
            for o in options
        ],
        "multi_select": False,
    }


def paragraph(content: str) -> dict[str, Any]:
    return {
        "key": "info", "label": None, "type": "paragraph", "readonly": True,
        "placeholder": None, "content": content,
    }


def _api_key(settings: dict[str, Any], prefix: str) -> str:
    return str(settings.get(f"{prefix}_api_key") or settings.get("api_key") or "-")


def _string(settings: dict[str, Any], key: str, default: str) -> str:
    return str(settings.get(key) or default)


def _float(settings: dict[str, Any], key: str, default: float) -> float:
    try:
        value = settings.get(key, default)
        return default if value is None or value == "" else float(value)
    except (TypeError, ValueError):
        return default


def _bool(settings: dict[str, Any], key: str, default: bool) -> bool:
    value = settings.get(key, default)
    return value if isinstance(value, bool) else default


# ── Response envelope ────────────────────────────────────────────────────────


class ClineEnvelopeTransport(httpx.BaseTransport):
    """Unwrap Cline's response envelope so the OpenAI SDK can parse it.

    {"success": true, "data": {...}} becomes the bare completion.
    {"success": false, "error": ...} becomes an OpenAI-style
    {"error": {"message": ...}} body, and a 200 status is turned into a 502
    so the failure is reported instead of being read as an empty reply.
    """

    def __init__(self, inner: httpx.BaseTransport | None = None):
        self._inner = inner or httpx.HTTPTransport()

    @override
    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = self._inner.handle_request(request)
        if "application/json" not in response.headers.get("content-type", ""):
            return response

        response.read()
        try:
            body = json.loads(response.content)
        except ValueError:
            return response
        if not isinstance(body, dict) or "success" not in body:
            return response

        status = response.status_code
        if body["success"] is True and isinstance(body.get("data"), dict):
            payload: Any = body["data"]
        elif body["success"] is False:
            error = body.get("error") or body.get("message") or "Cline request failed"
            message = error.get("message", json.dumps(error)) if isinstance(error, dict) else str(error)
            payload = {"error": {"message": message}}
            if status < 400:
                status = 502
        else:
            return response

        # response.read() already decoded the body, so drop the encoding and
        # length headers that described the original bytes
        headers = [
            (name, value) for name, value in response.headers.raw
            if name.lower() not in (b"content-length", b"content-encoding")
        ]
        return httpx.Response(
            status,
            headers=headers,
            content=json.dumps(payload).encode("utf-8"),
            request=request,
            extensions=response.extensions,
        )

    @override
    def close(self) -> None:
        self._inner.close()


class ClineLLMModel(OpenAILLMModel):
    def __init__(self, base_url: str, api_key: str, *args: Any, tools_enabled: bool = True, **kwargs: Any):
        super().__init__(base_url, api_key, *args, **kwargs)
        self.tools_enabled = tools_enabled
        self.client = OpenAI(
            base_url=base_url,
            api_key=api_key,
            max_retries=4,
            http_client=DefaultHttpxClient(transport=ClineEnvelopeTransport()),
        )

    def generate(self, messages: List[dict], tools: Optional[List[dict]] = None,
                 tool_choice: Optional[Any] = None):
        return super().generate(
            messages,
            tools if self.tools_enabled else None,
            tool_choice if self.tools_enabled else None,
        )


# ── Plugin ───────────────────────────────────────────────────────────────────


class ClinePlugin(PluginBase):
    @override
    def __init__(self, plugin_manifest: PluginManifest):
        super().__init__(plugin_manifest)
        providers: list[dict[str, Any]] = []
        for provider_id, prefix, slot, title in (
            ("llm", "llm", "llm", "Cline LLM"),
            ("agent-llm", "agent_llm", "agent_llm", "Cline Agent LLM"),
        ):
            providers.append({
                "kind": "llm", "id": provider_id, "label": "Cline", "slots": [slot],
                "settings_config": [{"key": prefix, "label": title, "fields": [
                    text_field("api_key", "Cline API Key", "", hidden=True),
                    text_field(f"{prefix}_api_key", "Override API Key", "", hidden=True),
                    text_field(f"{prefix}_model", "Model", CLINE_MODEL),
                    number_field(f"{prefix}_temperature", "Temperature", 1.0, 0.0, 2.0, 0.01),
                    select_field(f"{prefix}_reasoning_effort", "Reasoning Effort", "default", REASONING_EFFORTS),
                    toggle_field(f"{prefix}_tools_enabled", "Enable Tool Use", True),
                    paragraph("Disable tool use if the selected model rejects tool definitions."),
                ]}],
            })
        providers.append({
            "kind": "vlm", "id": "vlm", "label": "Cline", "slots": ["vision"],
            "settings_config": [{"key": "vlm", "label": "Cline Vision", "fields": [
                text_field("api_key", "Cline API Key", "", hidden=True),
                text_field("vlm_api_key", "Override API Key", "", hidden=True),
                text_field("vlm_model", "Model", CLINE_VLM_MODEL),
                number_field("vlm_temperature", "Temperature", 1.0, 0.0, 2.0, 0.01),
                select_field("vlm_reasoning_effort", "Reasoning Effort", "none", REASONING_EFFORTS),
                paragraph("Pick a model that accepts images. ClinePass models such as cline-pass/glm-5.3 are text-only and ignore the screenshot."),
            ]}],
        })
        self.model_providers = providers  # type: ignore[assignment]

    @override
    def create_model(self, provider_id: str, settings: dict[str, Any]):
        if provider_id == "vlm":
            return ClineLLMModel(
                CLINE_API_URL,
                _api_key(settings, "vlm"),
                _string(settings, "vlm_model", CLINE_VLM_MODEL),
                _float(settings, "vlm_temperature", 1.0),
                reasoning_effort=_string(settings, "vlm_reasoning_effort", "none"),
                provider_name="cline",
                tools_enabled=False,
            )
        if provider_id not in {"llm", "agent-llm"}:
            raise ValueError(f"Unknown Cline model provider: {provider_id}")
        prefix = "agent_llm" if provider_id == "agent-llm" else "llm"
        return ClineLLMModel(
            CLINE_API_URL,
            _api_key(settings, prefix),
            _string(settings, f"{prefix}_model", CLINE_MODEL),
            _float(settings, f"{prefix}_temperature", 1.0),
            reasoning_effort=_string(settings, f"{prefix}_reasoning_effort", "default"),
            provider_name="cline",
            tools_enabled=_bool(settings, f"{prefix}_tools_enabled", True),
        )
