# COVAS:NEXT Cline Plugin

[Cline API](https://docs.cline.bot/api/overview) (`api.cline.bot`) as a model provider for COVAS:NEXT.

Cline's API is OpenAI-compatible except that it wraps every response in
`{"success": true, "data": {...}}`. Pointed at Cline through the *Custom
OpenAI-compatible* provider, COVAS:NEXT therefore reads every reply as empty.
This plugin unwraps the envelope, so replies, tool calls and token usage all
work.

## Features

- **Main LLM** and **Agent LLM**: any Cline model, including ClinePass models (default `cline-pass/glm-5.3`)
- **Vision**: screenshot descriptions through an image-capable Cline model (default `google/gemini-3.8-flash`)
- Tool-use toggle per slot, for models that reject tool definitions
- Cline errors (out of credits, model failures, ...) show up as errors instead of silent empty replies

Not supported: **Embeddings / Logbook**. Cline has no embeddings endpoint, so
choose another embedding provider.

## Requirements

A COVAS:NEXT version with provider plugins (the provider dropdowns list
plugin providers). No extra Python packages: the plugin only uses `openai`
and `httpx`, which ship with COVAS:NEXT.

## Installation

Download `cn-plugin-cline-<version>.zip` from *Releases* and extract it into
the COVAS:NEXT plugins folder:

* Windows: `%appdata%\com.covas-next.ui\plugins`
* Linux: `~/.var/app/com.covasnext.ui/data/com.covas-next.ui/plugins`

The zip contains a `cn-plugin-cline` folder, giving:

* `plugins`
    * `cn-plugin-cline`
        * `cn-plugin-cline.py`
        * `manifest.json`
        * `__init__.py`
        * `README.md`

Restart COVAS:NEXT. **Cline** then appears in the LLM, Agent LLM and Vision
provider dropdowns.

## Configuration

Create an API key at [app.cline.bot](https://app.cline.bot) under
*Settings → API Keys*. Enter it once as **Cline API Key**; each slot can
override it.

| Slot | Setting | Default |
|------|---------|---------|
| LLM / Agent LLM | Model | `cline-pass/glm-5.3` |
| | Temperature | 1.0 |
| | Reasoning Effort | default |
| | Enable Tool Use | on |
| Vision | Model | `google/gemini-3.8-flash` |
| | Temperature | 1.0 |
| | Reasoning Effort | none |

Model names use Cline's `provider/model` form. The full list:
`curl https://api.cline.bot/api/v1/models`.

**Vision needs a model that accepts images.** ClinePass models such as
`cline-pass/glm-5.3` are text-only, and Cline drops the image silently: the
model just replies that it sees no image.

## Development

Tests need the COVAS:NEXT source for `lib.*`. Check it out next to this repo
(`../Elite-Dangerous-AI-Integration`) or point `COVAS_SRC` at its `src`
folder, install its `requirements.txt` into a Python 3.12 environment, then:

```bash
python -m pytest tests
```

See the [COVAS:NEXT Plugin Development Guide](https://ratherrude.github.io/Elite-Dangerous-AI-Integration/plugins/Development/).

## Packaging and releasing

`./pack.ps1` or `./pack.sh` builds `dist/cn-plugin-cline.zip`.

Pushing a `v*` tag runs the tests against the latest COVAS:NEXT, packages the
plugin and creates a GitHub Release with the zip attached:

```bash
git tag v0.1.0
git push origin v0.1.0
```

## Acknowledgements

- [COVAS:NEXT](https://github.com/RatherRude/Elite-Dangerous-AI-Integration)
- Structure based on [COVAS-Labs/plugin-elevenlabs](https://github.com/COVAS-Labs/plugin-elevenlabs)
