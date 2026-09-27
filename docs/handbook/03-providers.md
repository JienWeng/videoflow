# 3. Configure providers

[Handbook](README.md) · Previous: [Install](02-installation.md) · Next: [Projects](04-projects.md)

VideoFlow has three separate AI jobs: text planning, image generation, and video generation. Vision QA is another model assignment. A working text connection does not prove image or video generation is ready.

## Understand the current defaults

| Job | Current implementation default | Where to configure |
|---|---|---|
| Story and planning agents | OpenCode Go, `deepseek-v4-flash` | Settings → Providers, then Agents |
| Vision QA | AtlasCloud, `qwen/qwen3-vl-30b-a3b-instruct` | Settings → Agents |
| Character and prop images | AtlasCloud | AtlasCloud credentials; these services currently select it directly |
| Storyboard images | AtlasCloud, optionally OpenRouter | Settings → Engines |
| Whole-scene video | AtlasCloud H3, optionally OpenRouter | Settings → Engines |

These are configured IDs from the source, not verified recommendations or guarantees of account access. Confirm availability in your provider account. The initial account setup is: sign in on the provider website, create an API key, and enable the account usage needed by your chosen models. Keep the key private.

For the current full authoring path, configure AtlasCloud plus a working text provider. You can use OpenRouter for text while retaining AtlasCloud for media. **An OpenRouter-only setup is not currently complete.** See the [compatibility report](../audits/2026-09-27-openrouter.md).

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

## OpenRouter media: experimental path

The code has image/video adapters, but several blockers remain: AtlasCloud reference uploads, character/prop routing, video download authentication, reference semantics, model capability validation, and inconsistent setting resolution. Use the compatibility report to assess these before spending on a render.

The UI saves a suggested video model when changing the provider. Setting only `DEFAULT_VIDEO_PROVIDER=openrouter` in `.env` can still resolve the AtlasCloud `video_model` default. Explicitly inspect the resolved model in Engines. For OpenRouter image generation, the adapter currently reads `OPENROUTER_IMAGE_MODEL`, rather than the UI's `image_model` value; edit the environment and restart when testing that path.

## How saved settings behave

App values resolve in this order: project override → global saved value → configuration default. Provider database credentials take precedence over environment credentials. Clearing a saved key can reveal the environment key again; it does not necessarily disconnect the provider. API credentials in SQLite are base64-obfuscated, not encrypted.

Settings contain Providers, Engines, Defaults, Agents, and Appearance. Start with credentials and agent routing, then media engines; use Defaults for durations, language, and captions, and Appearance for theme.

The optional local Codex connection depends on a compatible authenticated CLI on the API machine. It is not needed for this guide; CLI/model compatibility was not validated in this audit.

**Expected result:** selected agents point to configured connections and their model checks succeed. Complete a small workflow only after reviewing the media limitations. For authentication or schema errors, see [Troubleshooting](11-troubleshooting.md).
