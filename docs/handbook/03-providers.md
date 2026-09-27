# 3. Configure providers

[Handbook](README.md) · Previous: [Install](02-installation.md) · Next: [Projects](04-projects.md)

VideoFlow has three separate AI jobs: text planning, image generation, and video generation. Vision QA is another model assignment. A working text connection does not prove image or video generation is ready.

## Understand the current defaults

| Job | Current implementation default | Where to configure |
|---|---|---|
| Story and planning agents | OpenCode Go, `deepseek-v4-flash` | Settings → Providers, then Agents |
| Vision QA | AtlasCloud, `qwen/qwen3-vl-30b-a3b-instruct` | Settings → Agents |
| Character and prop images | AtlasCloud or OpenRouter | Settings → Engines |
| Storyboard images | AtlasCloud or OpenRouter | Settings → Engines |
| Whole-scene and shot video | AtlasCloud H3 or OpenRouter | Settings → Engines |

These are configured IDs from the source, not verified recommendations or guarantees of account access. Confirm availability in your provider account. The initial account setup is: sign in on the provider website, create an API key, and enable the account usage needed by your chosen models. Keep the key private.

OpenRouter can be selected for image and video media as well as text. Configure the built-in OpenRouter credential for media; named text connections keep independent credentials. Actual account/model behavior still needs a live smoke test, and local image references sent to video models use data URLs whose support is not specified in OpenRouter's video guide. See the [compatibility report](../audits/2026-09-27-openrouter.md).

## Configure a text connection

1. Open **Settings → Providers**.
2. Use a built-in provider, or fill **Add a named connection** with a descriptive name and preset.
3. Choose a model ID from that provider. A model name is not an API key.
4. Save the API key. For a custom endpoint, confirm its base URL and protocol.
5. Use **Load models** where available. Manual IDs are supported when discovery is unavailable.
6. Run the connection check, then **Test model + JSON** for your chosen model. The latter makes a real request and consumes provider usage.
7. Open **Agents** and assign the connection and model to each text agent you want to use. Saving a key alone does not reroute agents from their defaults.
8. Assign a model that accepts image inputs to QA. A successful text/JSON test does not verify vision.

For built-in OpenRouter text routing, use `https://openrouter.ai/api/v1` and an available text model. If a model rejects tool output, a named Chat Completions connection can choose JSON mode or schema-in-prompt output. All results still go through local schema validation and retries.

Named connections are LLM routes. A named OpenRouter connection's independently saved key is not automatically the built-in OpenRouter media credential. Configure the built-in OpenRouter entry when testing its media integration.

## Configure AtlasCloud media

Set `ATLASCLOUD_API_KEY` in `.env`, or save the AtlasCloud provider key in Settings. The environment distinguishes the media base URL (`ATLASCLOUD_BASE_URL`, ending `/api/v1`) from the LLM base URL (`ATLAS_LLM_BASE_URL`, ending `/v1`). Keep those endpoint roles separate.

In **Engines**, inspect the image/video provider and model. The current AtlasCloud video adapter sends H3-shaped text-to-video payloads. Changing its model field to a legacy Kling model does not restore the old Kling adapter. Image references and sound controls in stored render specs do not all reach H3.

## OpenRouter media

Changing the provider in Engines selects the corresponding media model. The model is checked against OpenRouter's video model catalog before submission; unsupported duration or aspect ratio values return the supported values. Image guidance references and explicit first/last-frame anchors are sent through their separate API fields. The worker downloads completed videos through OpenRouter's authenticated content endpoint.

Local image assets are embedded as data URLs, avoiding an AtlasCloud upload. OpenRouter's image guide documents data URLs for image references; its video guide only shows ordinary URLs, so test a reference-image video on your account/model before relying on it. OpenRouter video references do not accept a reference video asset. Multi-shot specs are expressed as a timed shot sequence in the prompt because the dedicated endpoint has no native multi-shot field.

## How saved settings behave

App values resolve in this order: project override → global saved value → configuration default. Provider database credentials take precedence over environment credentials. Clearing a saved key can reveal the environment key again; it does not necessarily disconnect the provider. API credentials in SQLite are base64-obfuscated, not encrypted.

Settings contain Providers, Engines, Defaults, Agents, and Appearance. Start with credentials and agent routing, then media engines; use Defaults for durations, language, and captions, and Appearance for theme.

The optional local Codex connection depends on a compatible authenticated CLI on the API machine. It is not needed for this guide; CLI/model compatibility was not validated in this audit.

**Expected result:** selected agents point to configured connections and their model checks succeed. Complete a small workflow only after reviewing the media limitations. For authentication or schema errors, see [Troubleshooting](11-troubleshooting.md).
