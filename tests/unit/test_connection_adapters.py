from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel
from app.config import Settings
from app.llm.connection_client import ConnectionClient
from app.llm.structured_client import StructuredLLMClient
from app.errors import ProviderError
from app.llm.connections import definition


class Answer(BaseModel):
    answer: str


def test_opencode_go_deepseek_uses_chat_protocol():
    entry = definition("opencode-go")
    assert entry["protocol"] == "chat"
    assert entry["model"] == "deepseek-v4-flash"


async def test_responses_validates_retries_and_maps_images(monkeypatch):
    create = AsyncMock(side_effect=[SimpleNamespace(output_text='invalid'), SimpleNamespace(output_text='{"answer":"yes"}')])
    sdk = AsyncMock()
    sdk.__aenter__.return_value.responses.create = create
    monkeypatch.setattr('openai.AsyncOpenAI', lambda **kw: sdk)
    monkeypatch.setattr('app.llm.providers._resolved_creds', lambda *a: ('key', 'https://gateway/v1'))
    client = ConnectionClient('opencode', Settings(_env_file=None), 5)
    out = await client.create(model='model', response_model=Answer, messages=[{'role': 'user', 'content': [
        {'type': 'text', 'text': 'Describe'}, {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,YQ=='}}]}])
    assert out.answer == 'yes'
    assert create.await_count == 2
    assert create.call_args.kwargs['input'][1]['content'][1]['type'] == 'input_image'


async def test_claude_vision_conversion(monkeypatch):
    client = StructuredLLMClient(Settings(_env_file=None))
    create = AsyncMock(return_value=Answer(answer='yes'))
    backend = SimpleNamespace(kind='anthropic', client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    monkeypatch.setattr(client, '_backend', lambda *a: backend)
    await client.generate(provider='anthropic', model='claude-test', response_model=Answer, user_prompt='Describe', images=['data:image/png;base64,YQ=='])
    image = create.call_args.kwargs['messages'][-1]['content'][1]
    assert image == {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png', 'data': 'YQ=='}}


async def test_codex_missing_login_fails_without_subprocess(monkeypatch):
    monkeypatch.setattr('app.llm.connection_client.codex_status', lambda: False)
    spawn = AsyncMock()
    monkeypatch.setattr('asyncio.create_subprocess_exec', spawn)
    with pytest.raises(ProviderError, match='codex login'):
        await ConnectionClient('codex', Settings(_env_file=None), 5).create(model='model', response_model=Answer, messages=[])
    spawn.assert_not_called()


async def test_codex_exec_is_bounded_and_validates_output(monkeypatch):
    from pathlib import Path
    monkeypatch.setattr('app.llm.connection_client.codex_status', lambda: True)
    captured = {}
    async def spawn(*args, **kwargs):
        captured.update(args=args, kwargs=kwargs)
        Path(args[args.index('--output-last-message') + 1]).write_text('{"answer":"yes"}')
        return SimpleNamespace(returncode=0, communicate=AsyncMock(return_value=(b'', b'')))
    monkeypatch.setattr('asyncio.create_subprocess_exec', spawn)
    out = await ConnectionClient('codex', Settings(_env_file=None), 5).create(model='chosen-model', response_model=Answer, messages=[{'role': 'user', 'content': 'hi'}])
    assert out.answer == 'yes'
    assert '--ignore-user-config' in captured['args']
    assert 'read-only' in captured['args']
    assert 'chosen-model' in captured['args']
    assert 'OPENAI_API_KEY' not in captured['kwargs']['env']
