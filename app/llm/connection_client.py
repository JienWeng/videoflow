"""Responses and local Codex adapters with the existing schema contract."""
from __future__ import annotations

import asyncio
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from app.errors import ProviderError
from app.llm.connections import definition, request_headers


def codex_status() -> bool:
    if not shutil.which("codex"):
        return False
    try:
        result = subprocess.run(["codex", "login", "status"], capture_output=True, text=True, timeout=5)
        return result.returncode == 0 and "chatgpt" in (result.stdout + result.stderr).lower()
    except (OSError, subprocess.TimeoutExpired):
        return False


class ConnectionClient:
    def __init__(self, provider, settings, timeout):
        self.provider, self.settings, self.timeout = provider, settings, timeout
        self.chat = self.completions = self

    async def create(self, *, model, response_model, messages, **kwargs):
        if definition(self.provider)["protocol"] == "codex":
            return await self._codex(model, response_model, messages)
        from openai import AsyncOpenAI
        from app.llm.providers import _resolved_creds
        key, url = _resolved_creds(self.provider, self.settings)
        if not key:
            raise ProviderError("API key is not configured")
        inputs = []
        for message in messages:
            content = message["content"]
            if isinstance(content, list):
                content = [
                    {"type": "input_text", "text": part["text"]} if part["type"] == "text" else
                    {"type": "input_image", "image_url": part["image_url"]["url"]}
                    for part in content
                ]
            inputs.append({"role": message["role"], "content": content})
        # Validation/retry stays local even when a gateway lacks strict JSON Schema.
        inputs.insert(0, {"role": "system", "content": "Return ONLY JSON matching this schema: " + json.dumps(response_model.model_json_schema())})
        async with AsyncOpenAI(api_key=key, base_url=url, timeout=self.timeout, default_headers=request_headers(self.provider)) as client:
            for attempt in range(min(kwargs.get("max_retries", 3), 5) + 1):
                result = await client.responses.create(model=model, input=inputs)
                try:
                    return response_model.model_validate_json(result.output_text)
                except ValueError:
                    if attempt == min(kwargs.get("max_retries", 3), 5):
                        raise ProviderError("Model did not return valid structured output") from None
                    inputs.append({"role": "user", "content": "Previous response did not match the schema. Return a valid JSON object only."})

    async def _codex(self, model, response_model, messages):
        if not await asyncio.to_thread(codex_status):
            raise ProviderError("Run codex login on this computer using ChatGPT first")
        with tempfile.TemporaryDirectory(prefix="videoflow-codex-") as folder:
            root = Path(folder)
            schema, output = root / "schema.json", root / "output.json"
            schema.write_text(json.dumps(response_model.model_json_schema()))
            args = ["codex", "exec", "--ignore-user-config", "--ignore-rules", "--ephemeral",
                    "--skip-git-repo-check", "--sandbox", "read-only", "--color", "never",
                    "-c", "features.shell_tool=false", "-c", "web_search=\"disabled\"",
                    "--model", model, "--output-schema", str(schema), "--output-last-message", str(output)]
            prompt = ["Return the requested JSON. Do not execute commands, use tools, or inspect files."]
            for message in messages:
                content = message["content"]
                if isinstance(content, str):
                    prompt.append(message["role"] + ": " + content)
                    continue
                for part in content:
                    if part["type"] == "text":
                        prompt.append(part["text"])
                    else:
                        url = part["image_url"]["url"]
                        if not url.startswith("data:image/"):
                            raise ProviderError("Codex requires uploaded/local reference images, not remote image URLs")
                        path = root / f"image-{len(args)}.png"
                        path.write_bytes(base64.b64decode(url.split(",", 1)[1]))
                        args.extend(["--image", str(path)])
            args.append("-")
            env = {k: v for k, v in os.environ.items() if k not in ("OPENAI_API_KEY", "OPENAI_BASE_URL")}
            proc = await asyncio.create_subprocess_exec(*args, cwd=folder, env=env,
                                                       stdin=asyncio.subprocess.PIPE,
                                                       stdout=asyncio.subprocess.DEVNULL,
                                                       stderr=asyncio.subprocess.DEVNULL)
            try:
                await asyncio.wait_for(proc.communicate("\n".join(prompt).encode()), self.timeout)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                if proc.returncode is None:
                    proc.kill()
                await proc.wait()
                raise
            if proc.returncode or not output.exists():
                raise ProviderError("Codex request failed: check login, selected model access, and subscription usage limits")
            return response_model.model_validate_json(output.read_text())
