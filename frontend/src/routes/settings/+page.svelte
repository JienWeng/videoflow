<script lang="ts">
  import { onMount } from 'svelte';
  import { get, put, post } from '$lib/api';
  import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '$lib/components/ui/card';
  import { Badge } from '$lib/components/ui/badge';
  import { Button } from '$lib/components/ui/button';
  import { Input } from '$lib/components/ui/input';
  import { Separator } from '$lib/components/ui/separator';
  import { Tabs, TabsList, TabsTrigger, TabsContent } from '$lib/components/ui/tabs';
  import { Skeleton } from '$lib/components/ui/skeleton';
  import { toast } from 'svelte-sonner';
  import {
    RotateCcw,
    Plug,
    KeyRound,
    Sparkles,
    Palette,
    Sun,
    Moon,
    Monitor,
    Plus,
    Trash2,
    LoaderCircle,
    CircleCheck,
    Wifi
  } from '@lucide/svelte';

  // -------------------------------------------------------------- types
  type Agent = {
    agent: string;
    label: string;
    provider: string;
    model: string;
    default_provider: string;
    default_model: string;
  };
  type Provider = {
    name: string;
    label?: string;
    protocol?: string;
    configured: boolean;
    models: string[];
    suggested_models: string[];
    default_model: string;
    allow_custom: boolean;
    from_db: boolean;
  };
  type ProviderConfig = {
    name: string;
    configured: boolean;
    masked_key: string;
    base_url: string | null;
    from_db: boolean;
  };
  type AppSettings = {
    default_aspect_ratio: string;
    default_scene_duration: number;
    caption_style: string;
    caption_language: string;
    whisper_model: string;
    dialogue_language: string;
    image_model: string;
    ref_image_model: string;
    video_model: string;
    vl_model: string;
    max_video_refs: number;
    render_negatives: string[];
  };
  type TestResult = { ok: boolean; latency_ms: number | null; error: string | null };
  type ProviderPreset = {
    label: string;
    protocol: 'chat' | 'responses' | 'anthropic' | 'codex';
    url: string;
    model: string;
    preset: string;
    mode: 'auto' | 'tools' | 'json' | 'prompt';
    vision: boolean;
  };

  // -------------------------------------------------------------- state
  let agents = $state<Agent[]>([]);
  let providers = $state<Provider[]>([]);
  let app = $state<AppSettings | null>(null);
  let loaded = $state(false);
  let error = $state('');
  let busy = $state('');
  let presets = $state<Record<string, any>>({});
  let newLabel = $state('');
  let newPreset = $state('openai');
  let newProtocol = $state('chat');
  let newUrl = $state('https://api.openai.com/v1');
  let newModel = $state('gpt-5.6-luna');
  let newMode = $state('auto');
  let newVision = $state(true);
  function choosePreset() {
    const p = presets[newPreset];
    if (!p) return;
    newProtocol = p.protocol; newUrl = p.url ?? ''; newModel = p.model;
  }
  async function addConnection() {
    busy = 'add-connection';
    try {
      await post('/settings/connections', { label: newLabel.trim(), preset: newPreset,
        protocol: newProtocol, base_url: newUrl || null, model: newModel.trim(), mode: newMode, vision: newVision });
      newLabel = '';
      await refresh();
      toast.success('Connection added. Configure its credentials below, then assign agents.');
    } catch (e: any) { toast.error(e.message); }
    finally { busy = ''; }
  }
  async function discoverModels(name: string) {
    busy = `models-${name}`;
    try {
      const result = await get(providerEndpoint(name, 'models'));
      if (result.error) { toast.error(result.error); return; }
      providers = providers.map(p => p.name === name ? {...p, suggested_models: result.models, models: result.models} : p);
      if (result.models.length) {
        testModelInput[name] = result.models[0];
        providerModelInput[name] = false;
      }
      toast.success(`Loaded ${result.models.length} models for agent selection`);
    } catch (e: any) { toast.error(e.message); }
    finally { busy = ''; }
  }

  // Per-provider editable form fields (key/base_url) + configured pill state.
  let provCfg = $state<Record<string, ProviderConfig>>({});
  let provKeyInput = $state<Record<string, string>>({});
  let provUrlInput = $state<Record<string, string>>({});
  let provTest = $state<Record<string, TestResult | undefined>>({});
  let testModelInput = $state<Record<string, string>>({});
  async function verifyModel(name: string) {
    busy = `verify-${name}`;
    try {
      const result = await post(providerEndpoint(name, 'verify-model'), {model: testModelInput[name]?.trim()});
      if (result.ok) toast.success('Model returned valid structured JSON');
      else toast.error(result.error);
    } catch (e: any) { toast.error(e.message); }
    finally { busy = ''; }
  }

  // Theme radio — persisted to the shared localStorage key the shell reads.
  const THEME_KEY = 'videoflow.theme';
  let theme = $state<'light' | 'dark' | 'system'>('system');

  // Active settings tab (bound so clicking a trigger switches sections).
  let tab = $state('providers');

  // ------------------------------------------------------------- labels
  const providerLabels: Record<string, string> = {
    minimax: 'MiniMax',
    openai: 'OpenAI',
    anthropic: 'Anthropic',
    gemini: 'Gemini',
    atlas: 'AtlasCloud'
  };
  const PROVIDER_ORDER = ['minimax', 'atlas', 'openai', 'anthropic', 'gemini'];
  const FALLBACK_PRESETS: Record<string, ProviderPreset> = {
    minimax: { label: 'MiniMax', protocol: 'chat', url: 'https://api.minimax.io/v1', model: 'MiniMax-Text-01', preset: 'minimax', mode: 'auto', vision: true },
    openai: { label: 'OpenAI API', protocol: 'chat', url: 'https://api.openai.com/v1', model: 'gpt-5.6-luna', preset: 'openai', mode: 'auto', vision: true },
    anthropic: { label: 'Anthropic / Claude', protocol: 'anthropic', url: 'https://api.anthropic.com', model: 'claude-sonnet-4-6', preset: 'anthropic', mode: 'auto', vision: true },
    gemini: { label: 'Google Gemini', protocol: 'chat', url: 'https://generativelanguage.googleapis.com/v1beta/openai', model: 'gemini-2.5-flash', preset: 'gemini', mode: 'auto', vision: true },
    atlas: { label: 'AtlasCloud', protocol: 'chat', url: 'https://api.atlascloud.ai/v1', model: 'qwen/qwen3-vl-30b-a3b-instruct', preset: 'atlas', mode: 'auto', vision: true },
    openrouter: { label: 'OpenRouter', protocol: 'chat', url: 'https://openrouter.ai/api/v1', model: '', preset: 'openrouter', mode: 'auto', vision: true },
    deepseek: { label: 'DeepSeek', protocol: 'chat', url: 'https://api.deepseek.com', model: 'deepseek-chat', preset: 'deepseek', mode: 'auto', vision: true },
    opencode: { label: 'OpenCode Zen', protocol: 'responses', url: 'https://opencode.ai/zen/v1', model: '', preset: 'opencode', mode: 'auto', vision: true },
    'opencode-go': { label: 'OpenCode Go', protocol: 'chat', url: 'https://opencode.ai/zen/go/v1', model: '', preset: 'opencode-go', mode: 'auto', vision: true },
    codex: { label: 'ChatGPT via Codex', protocol: 'codex', url: '', model: 'gpt-5.6-luna', preset: 'codex', mode: 'auto', vision: true },
    custom: { label: 'Custom endpoint', protocol: 'chat', url: '', model: '', preset: 'custom', mode: 'auto', vision: true },
  };

  // One-line descriptions for each agent, plus a text/vision split.
  const VISION_AGENTS = new Set(['qa_agent', 'asset_recogniser']);
  const agentDesc: Record<string, string> = {
    script_agent: 'Turns your idea into a structured script.',
    scene_agent: 'Breaks the script into scenes.',
    shot_agent: 'Plans the shots within each scene.',
    prompt_agent: 'Writes the image / video generation prompts.',
    qa_agent: 'Looks at rendered frames and flags problems.',
    idea_agent: 'Develops and expands the core idea.',
    asset_planner: 'Decides which assets a scene needs.',
    refine_agent: 'Edits and refines copy on request.',
    intent_agent: 'Classifies what you are asking for.',
    asset_recogniser: 'Identifies characters / objects in images.',
    character_memory: 'Maintains the character bible.',
    style_agent: 'Designs the visual style.'
  };

  // -------------------------------------------------------------- options
  const ASPECT_RATIOS = ['9:16', '16:9', '1:1'];
  const WHISPER_MODELS = ['tiny', 'base', 'small', 'medium', 'large-v3'];
  const CAPTION_STYLES = ['default', 'bold', 'minimal', 'karaoke'];
  const CAPTION_LANGUAGES = [
    { value: 'auto', label: 'Auto-detect' },
    { value: 'zh', label: 'Chinese' },
    { value: 'en', label: 'English' }
  ];
  const DIALOGUE_LANGUAGES = [
    { value: 'zh', label: 'Chinese' },
    { value: 'en', label: 'English' }
  ];
  const CUSTOM = '__custom__';
  const LOAD_MODELS = '__load_models__';

  const selectablePresets = $derived(() => {
    const entries = Object.entries(presets).filter(([id, preset]) => (preset as any).preset === id);
    return entries.length ? entries : Object.entries(FALLBACK_PRESETS);
  });

  function providerEndpoint(name: string, suffix?: string): string {
    const base = `/settings/providers/${encodeURIComponent(name)}`;
    return suffix ? `${base}/${suffix}` : base;
  }

  // ------------------------------------------------------------- derived
  const byName = $derived(Object.fromEntries(providers.map((p) => [p.name, p])));
  const configuredProviders = $derived(
    providers.filter((p) => p.configured)
  );
  const orderedProviders = $derived(
    providers
  );
  const textAgents = $derived(agents.filter((a) => !VISION_AGENTS.has(a.agent)));
  const visionAgents = $derived(agents.filter((a) => VISION_AGENTS.has(a.agent)));

  // -------------------------------------------------------------- load
  async function refresh() {
    try {
      presets = await get('/settings/connection-presets');
    } catch {
      presets = FALLBACK_PRESETS;
    }
    const [ag, pv, ap] = await Promise.all([
      get('/settings/agents'),
      get('/settings/providers'),
      get('/settings/app')
    ]);
    agents = ag;
    providers = pv;
    testModelInput = Object.fromEntries(
      pv.map((p: Provider) => [p.name, p.models?.[0] ?? p.suggested_models?.[0] ?? p.default_model ?? ''])
    );
    for (const p of providers) providerLabels[p.name] = p.label ?? p.name;
    app = ap;
    // Load each provider's secret config (masked key + base_url) in parallel.
    const cfgs: ProviderConfig[] = await Promise.all(
      (pv as Provider[]).map((p) => get(providerEndpoint(p.name)))
    );
    const cfgMap: Record<string, ProviderConfig> = {};
    const keyMap: Record<string, string> = {};
    const urlMap: Record<string, string> = {};
    for (const c of cfgs) {
      cfgMap[c.name] = c;
      keyMap[c.name] = '';
      urlMap[c.name] = c.base_url ?? '';
    }
    provCfg = cfgMap;
    provKeyInput = keyMap;
    provUrlInput = urlMap;
  }

  onMount(() => {
    // Hydrate the theme radio from the shared key (fallback to system).
    try {
      const stored = localStorage.getItem(THEME_KEY);
      if (stored === 'light' || stored === 'dark' || stored === 'system') theme = stored;
    } catch {
      /* private mode / disabled storage */
    }
    refresh()
      .catch((e) => (error = e.message))
      .finally(() => (loaded = true));
  });

  // ------------------------------------------------------------- agents
  function isDefault(a: Agent): boolean {
    return a.provider === a.default_provider && a.model === a.default_model;
  }
  function suggestedFor(provider: string): string[] {
    return byName[provider]?.suggested_models ?? [];
  }

  async function saveAgent(a: Agent, provider: string, model: string) {
    busy = `agent-${a.agent}`;
    try {
      const updated = await put(`/settings/agents/${a.agent}`, { provider, model });
      agents = agents.map((x) => (x.agent === a.agent ? updated : x));
      toast.success(`${a.label} → ${providerLabels[provider] ?? provider} / ${model}`);
    } catch (e: any) {
      toast.error(e.message);
      await refresh().catch(() => {});
    } finally {
      busy = '';
    }
  }

  async function onAgentProvider(a: Agent, provider: string) {
    if (provider === a.provider) return;
    const model = byName[provider]?.default_model ?? suggestedFor(provider)[0];
    if (!model) {
      toast.error('No models available for this provider');
      return;
    }
    await saveAgent(a, provider, model);
  }

  // Free-typed model: select offers suggestions + a "Custom…" sentinel that
  // swaps the control for a text input.
  let agentCustomOpen = $state<Record<string, boolean>>({});
  let agentCustomVal = $state<Record<string, string>>({});

  function onAgentModelSelect(a: Agent, value: string) {
    if (value === CUSTOM) {
      agentCustomOpen[a.agent] = true;
      agentCustomVal[a.agent] = a.model;
      return;
    }
    agentCustomOpen[a.agent] = false;
    if (value !== a.model) saveAgent(a, a.provider, value);
  }
  function commitAgentCustom(a: Agent) {
    const m = (agentCustomVal[a.agent] ?? '').trim();
    agentCustomOpen[a.agent] = false;
    if (m && m !== a.model) saveAgent(a, a.provider, m);
  }

  async function resetAgent(a: Agent) {
    busy = `agent-${a.agent}`;
    try {
      const updated = await put(`/settings/agents/${a.agent}`, { provider: null, model: null });
      agents = agents.map((x) => (x.agent === a.agent ? updated : x));
      agentCustomOpen[a.agent] = false;
      toast.success(`${a.label} reset to default`);
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      busy = '';
    }
  }

  async function setAllText(provider: string) {
    if (!provider) return;
    const model = byName[provider]?.default_model ?? suggestedFor(provider)[0];
    if (!model) {
      toast.error('No models available for this provider');
      return;
    }
    busy = 'bulk-text';
    try {
      for (const a of textAgents) {
        const updated = await put(`/settings/agents/${a.agent}`, { provider, model });
        agents = agents.map((x) => (x.agent === a.agent ? updated : x));
      }
      toast.success(`All text agents → ${providerLabels[provider] ?? provider} / ${model}`);
    } catch (e: any) {
      toast.error(e.message);
      await refresh().catch(() => {});
    } finally {
      busy = '';
    }
  }

  async function resetAllAgents() {
    busy = 'bulk-reset';
    try {
      for (const a of agents) {
        const updated = await put(`/settings/agents/${a.agent}`, { provider: null, model: null });
        agents = agents.map((x) => (x.agent === a.agent ? updated : x));
      }
      agentCustomOpen = {};
      toast.success('All agents reset to defaults');
    } catch (e: any) {
      toast.error(e.message);
      await refresh().catch(() => {});
    } finally {
      busy = '';
    }
  }

  let bulkTextProvider = $state('');

  let providerModelInput = $state<Record<string, boolean>>({});
  let providerModelCustom = $state<Record<string, string>>({});

  function providerModelOptions(name: string): string[] {
    const p = byName[name];
    const dedup = new Map<string, true>();
    for (const m of [...(p?.models ?? []), ...(p?.suggested_models ?? [])]) {
      if (m) dedup.set(m, true);
    }
    if (p?.default_model) dedup.set(p.default_model, true);
    return [...dedup.keys()];
  }

  function onProviderModelSelect(name: string, value: string) {
    if (value === LOAD_MODELS) {
      discoverModels(name);
      return;
    }
    if (value === CUSTOM) {
      providerModelInput[name] = true;
      providerModelCustom[name] = testModelInput[name] ?? '';
      return;
    }
    providerModelInput[name] = false;
    testModelInput[name] = value;
  }

  function commitProviderCustomModel(name: string) {
    const m = (providerModelCustom[name] ?? '').trim();
    providerModelInput[name] = false;
    if (m) testModelInput[name] = m;
  }

  // ----------------------------------------------------------- providers
  async function saveProvider(name: string) {
    busy = `prov-${name}`;
    try {
      const body: { api_key?: string; base_url?: string } = {};
      // Only send api_key if the user typed something; an empty field leaves the
      // stored key untouched (so saving a base_url alone keeps the key).
      const k = provKeyInput[name] ?? '';
      if (k.trim()) body.api_key = k.trim();
      body.base_url = (provUrlInput[name] ?? '').trim();
      const updated: ProviderConfig = await put(providerEndpoint(name), body);
      provCfg[name] = updated;
      provKeyInput[name] = '';
      provUrlInput[name] = updated.base_url ?? '';
      // Reflect the new configured-state in the catalog (drives agent selects).
      providers = providers.map((p) =>
        p.name === name ? { ...p, configured: updated.configured, from_db: updated.from_db } : p
      );
      provTest[name] = undefined;
      toast.success(`${providerLabels[name] ?? name} saved`);
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      busy = '';
    }
  }

  async function clearProvider(name: string) {
    busy = `prov-${name}`;
    try {
      const updated: ProviderConfig = await put(providerEndpoint(name), { api_key: '' });
      provCfg[name] = updated;
      provKeyInput[name] = '';
      providers = providers.map((p) =>
        p.name === name ? { ...p, configured: updated.configured, from_db: updated.from_db } : p
      );
      provTest[name] = undefined;
      toast.success(`${providerLabels[name] ?? name} key cleared`);
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      busy = '';
    }
  }

  async function testProvider(name: string) {
    busy = `test-${name}`;
    provTest[name] = undefined;
    try {
      const res: TestResult = await post(providerEndpoint(name, 'test'));
      provTest[name] = res;
      if (res.ok) toast.success(`${providerLabels[name] ?? name}: connected (${res.latency_ms}ms)`);
      else toast.error(`${providerLabels[name] ?? name}: ${res.error ?? 'failed'}`);
    } catch (e: any) {
      provTest[name] = { ok: false, latency_ms: null, error: e.message };
      toast.error(e.message);
    } finally {
      busy = '';
    }
  }

  // -------------------------------------------------- app settings (engines/defaults)
  async function saveApp(patch: Partial<AppSettings>) {
    busy = 'app';
    try {
      const updated: AppSettings = await put('/settings/app', patch);
      app = updated;
      toast.success('Saved');
    } catch (e: any) {
      toast.error(e.message);
      await refresh().catch(() => {});
    } finally {
      busy = '';
    }
  }

  // Engine model fields: dropdown of suggested atlas models + "Custom…".
  // Atlas hosts the render models, so we draw suggestions from its catalog plus
  // the currently-saved value (so a custom id stays selected).
  function engineOptions(current: string): string[] {
    const atlas = byName['atlas']?.suggested_models ?? [];
    const set = new Set<string>(atlas);
    if (current) set.add(current);
    return [...set];
  }

  let engineCustomOpen = $state<Record<string, boolean>>({});
  let engineCustomVal = $state<Record<string, string>>({});

  function onEngineSelect(key: keyof AppSettings, value: string, current: string) {
    if (value === CUSTOM) {
      engineCustomOpen[key as string] = true;
      engineCustomVal[key as string] = current;
      return;
    }
    engineCustomOpen[key as string] = false;
    if (value !== current) saveApp({ [key]: value } as Partial<AppSettings>);
  }
  function commitEngineCustom(key: keyof AppSettings, current: string) {
    const v = (engineCustomVal[key as string] ?? '').trim();
    engineCustomOpen[key as string] = false;
    if (v && v !== current) saveApp({ [key]: v } as Partial<AppSettings>);
  }

  // Render negatives — editable list saved as a whole.
  let newNegative = $state('');
  function addNegative() {
    const v = newNegative.trim();
    if (!v || !app) return;
    if (app.render_negatives.includes(v)) {
      newNegative = '';
      return;
    }
    const next = [...app.render_negatives, v];
    newNegative = '';
    saveApp({ render_negatives: next });
  }
  function removeNegative(idx: number) {
    if (!app) return;
    const next = app.render_negatives.filter((_, i) => i !== idx);
    saveApp({ render_negatives: next });
  }

  // ------------------------------------------------------------- theme
  function setTheme(value: 'light' | 'dark' | 'system') {
    theme = value;
    try {
      localStorage.setItem(THEME_KEY, value);
    } catch {
      /* ignore */
    }
    // Data-attribute + class fallback so the choice applies immediately even
    // before the shell's ModeWatcher reacts. ModeWatcher owns the final state.
    const root = document.documentElement;
    root.setAttribute('data-theme', value);
    const prefersDark =
      typeof window !== 'undefined' &&
      window.matchMedia &&
      window.matchMedia('(prefers-color-scheme: dark)').matches;
    const dark = value === 'dark' || (value === 'system' && prefersDark);
    root.classList.toggle('dark', dark);
  }
</script>

<div class="p-6 max-w-3xl">
  <div class="mb-4">
    <h1 class="text-lg font-semibold">Settings</h1>
    <p class="text-sm text-muted-foreground">
      Configure providers, generation engines, defaults and agent routing.
    </p>
  </div>

  {#if error}
    <Card class="mb-4 border-destructive/40">
      <CardContent class="p-4 text-sm text-destructive">{error}</CardContent>
    </Card>
  {/if}

  {#if !loaded}
    <div class="space-y-3">
      {#each Array(6) as _, i (i)}
        <Skeleton class="h-16 w-full" />
      {/each}
    </div>
  {:else}
    <Tabs bind:value={tab} class="w-full">
      <TabsList class="mb-4">
        <TabsTrigger value="providers">Providers</TabsTrigger>
        <TabsTrigger value="engines">Engines</TabsTrigger>
        <TabsTrigger value="defaults">Defaults</TabsTrigger>
        <TabsTrigger value="agents">Agents</TabsTrigger>
        <TabsTrigger value="appearance">Appearance</TabsTrigger>
      </TabsList>

      <!-- ============================================ PROVIDERS -->
      <TabsContent value="providers">
        <Card>
          <CardHeader>
            <CardTitle class="flex items-center gap-2 text-base">
              <Plug class="size-4" />Providers
            </CardTitle>
            <CardDescription>
              Add an API key and (optionally) a custom base URL for each provider. Keys are stored on
              this machine and never shown again after saving.
            </CardDescription>
          </CardHeader>
          <CardContent class="space-y-5">
            <div class="rounded-lg border p-4 space-y-3">
              <h3 class="text-sm font-medium">Add a named connection</h3>
              <div class="grid gap-3 sm:grid-cols-2">
                <label class="text-xs">Name<Input bind:value={newLabel} placeholder="My OpenRouter" /></label>
                <label class="text-xs">Provider<select class="block w-full rounded border p-2 bg-background" bind:value={newPreset} onchange={choosePreset}>
                  {#each selectablePresets as [id, p]}<option value={id}>{p.label}</option>{/each}
                </select></label>
                <label class="text-xs">Protocol<select class="block w-full rounded border p-2 bg-background" bind:value={newProtocol}>
                  <option value="chat">OpenAI-compatible Chat Completions (includes Gemini)</option>
                  <option value="responses">OpenAI Responses</option><option value="anthropic">Anthropic Messages</option>
                  <option value="codex">ChatGPT via local Codex</option>
                </select></label>
                <label class="text-xs">Default model<Input bind:value={newModel} placeholder="Model ID from your provider" /></label>
                {#if newProtocol !== 'codex'}
                  <label class="text-xs">Base URL<Input bind:value={newUrl} /></label>
                  <label class="text-xs">Chat Completions output mode<select class="block w-full rounded border p-2 bg-background" bind:value={newMode} disabled={newProtocol !== 'chat'}>
                    <option value="auto">Provider default</option><option value="tools">Tool calling</option><option value="json">JSON mode</option><option value="prompt">JSON in prompt</option>
                  </select></label>
                {/if}
              </div>
              <label class="flex items-center gap-2 text-xs"><input type="checkbox" bind:checked={newVision} />Models on this connection accept images</label>
              <Button size="sm" disabled={!newLabel.trim() || busy === 'add-connection'} onclick={addConnection}>Add connection</Button>
            </div>
            {#each orderedProviders as p (p.name)}
              {@const cfg = provCfg[p.name]}
              {@const test = provTest[p.name]}
              <div data-provider={p.name}>
                <div class="mb-2 flex items-center gap-2">
                  <span class="text-sm font-medium">{providerLabels[p.name] ?? p.name}</span>
                  {#if cfg?.configured}
                    <Badge class="gap-1 text-[10px]">
                      <CircleCheck class="size-3" />Configured
                    </Badge>
                    {#if cfg.from_db}
                      <span class="text-[10px] text-muted-foreground">{cfg.masked_key}</span>
                    {:else}
                      <span class="text-[10px] text-muted-foreground">from environment</span>
                    {/if}
                  {:else}
                    <Badge variant="outline" class="text-[10px]">Not configured</Badge>
                  {/if}
                </div>

                {#if p.protocol === 'codex'}
                  <p class="text-sm text-muted-foreground">Uses the Codex CLI login on this computer. Run <code>codex login</code> in a terminal and sign in with ChatGPT. Refresh this page after login; run <code>codex logout</code> to disconnect. Test checks login only; model access is checked when an agent runs.</p>
                {:else}
                <div class="grid gap-2 sm:grid-cols-2">
                  <div>
                    <label class="mb-1 block text-xs text-muted-foreground" for="key-{p.name}">
                      API key
                    </label>
                    <div class="relative">
                      <KeyRound
                        class="absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground"
                      />
                      <Input
                        id="key-{p.name}"
                        type="password"
                        autocomplete="off"
                        class="pl-7"
                        placeholder={cfg?.configured ? '•••••• (leave blank to keep)' : 'Paste API key'}
                        bind:value={provKeyInput[p.name]}
                      />
                    </div>
                  </div>
                  <div>
                    <label class="mb-1 block text-xs text-muted-foreground" for="url-{p.name}">
                      Base URL (optional)
                    </label>
                    <Input
                      id="url-{p.name}"
                      autocomplete="off"
                      placeholder="default"
                      bind:value={provUrlInput[p.name]}
                    />
                  </div>
                </div>

                {/if}
                <div class="mt-2 flex flex-wrap items-center gap-2">
                  {#if providerModelInput[p.name]}
                    <Input
                      class="max-w-64"
                      aria-label={`Custom test model for ${p.label ?? p.name}`}
                      placeholder="Model ID to test"
                      bind:value={providerModelCustom[p.name]}
                      onkeydown={(e) => e.key === 'Enter' && commitProviderCustomModel(p.name)}
                    />
                    <Button
                      size="sm"
                      disabled={!providerModelCustom[p.name]?.trim() || busy === `verify-${p.name}`}
                      onclick={() => {
                        commitProviderCustomModel(p.name);
                        verifyModel(p.name);
                      }}
                    >
                      Verify
                    </Button>
                  {:else}
                    <select
                      aria-label={`Test model for ${p.label ?? p.name}`}
                      class="w-64 rounded-md border border-input bg-background px-2 py-1.5 text-sm"
                      disabled={!cfg?.configured || busy === `verify-${p.name}`}
                      value={testModelInput[p.name] ?? ''}
                      onchange={(e) => onProviderModelSelect(p.name, (e.currentTarget as HTMLSelectElement).value)}
                    >
                      {#if providerModelOptions(p.name).length}
                        {#each providerModelOptions(p.name) as m (m)}
                          <option value={m}>{m}</option>
                        {/each}
                      {:else}
                        <option value="" disabled>Load or enter model</option>
                      {/if}
                      <option value={LOAD_MODELS}>Load models…</option>
                      <option value={CUSTOM}>Custom…</option>
                    </select>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={!cfg?.configured || !testModelInput[p.name]?.trim() || busy === `verify-${p.name}`}
                      onclick={() => verifyModel(p.name)}
                    >
                      Verify
                    </Button>
                  {/if}
                  <span class="text-xs text-muted-foreground">Model tests consume provider usage.</span>
                  <Button
                    size="sm"
                    disabled={busy === `prov-${p.name}`}
                    onclick={() => saveProvider(p.name)}
                  >
                    {busy === `prov-${p.name}` ? 'Saving…' : 'Save'}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={busy === `test-${p.name}` || !cfg?.configured}
                    onclick={() => testProvider(p.name)}
                  >
                    {#if busy === `test-${p.name}`}
                      <LoaderCircle class="size-3.5 mr-1 animate-spin" />Testing…
                    {:else}
                      <Wifi class="size-3.5 mr-1" />Test connection
                    {/if}
                  </Button>
                  {#if cfg?.from_db}
                    <Button
                      size="sm"
                      variant="ghost"
                      class="text-destructive hover:text-destructive"
                      disabled={busy === `prov-${p.name}`}
                      onclick={() => clearProvider(p.name)}
                    >
                      Clear key
                    </Button>
                  {/if}

                  {#if test}
                    {#if test.ok}
                      <span class="flex items-center gap-1 text-xs text-emerald-500">
                        <CircleCheck class="size-3.5" />Connected
                        {#if test.latency_ms != null}({test.latency_ms}ms){/if}
                      </span>
                    {:else}
                      <span class="text-xs text-destructive">{test.error ?? 'Connection failed'}</span>
                    {/if}
                  {/if}
                </div>
              </div>
              {#if p.name !== orderedProviders[orderedProviders.length - 1].name}
                <Separator />
              {/if}
            {/each}
          </CardContent>
        </Card>
      </TabsContent>

      <!-- ============================================ ENGINES -->
      <TabsContent value="engines">
        <Card>
          <CardHeader>
            <CardTitle class="flex items-center gap-2 text-base">
              <Sparkles class="size-4" />Generation engines
            </CardTitle>
            <CardDescription>
              The models that actually generate your media. Pick a suggested model or type a custom
              id — the backend accepts any model the provider exposes.
            </CardDescription>
          </CardHeader>
          <CardContent class="space-y-4">
            {#if app}
              {@const engines = [
                { key: 'image_model', label: 'Image model', hint: 'Text-to-image generation.' },
                { key: 'ref_image_model', label: 'Reference image model', hint: 'Edits / character-sheet driven images.' },
                { key: 'video_model', label: 'Video model', hint: 'Image / reference to video.' },
                { key: 'vl_model', label: 'Vision model', hint: 'Reads frames for QA.' }
              ] as const}
              {#each engines as eng (eng.key)}
                {@const cur = app[eng.key] as string}
                <div class="flex flex-wrap items-center gap-3">
                  <div class="min-w-[180px] flex-1">
                    <div class="text-sm font-medium">{eng.label}</div>
                    <div class="text-[11px] text-muted-foreground">{eng.hint}</div>
                  </div>
                  <div class="flex items-center gap-2">
                    {#if engineCustomOpen[eng.key]}
                      <Input
                        class="h-8 w-64 text-sm"
                        placeholder="Custom model id"
                        bind:value={engineCustomVal[eng.key]}
                        onkeydown={(e) => e.key === 'Enter' && commitEngineCustom(eng.key, cur)}
                      />
                      <Button size="sm" disabled={busy === 'app'} onclick={() => commitEngineCustom(eng.key, cur)}>
                        Save
                      </Button>
                      <Button size="sm" variant="ghost" onclick={() => (engineCustomOpen[eng.key] = false)}>
                        Cancel
                      </Button>
                    {:else}
                      <select
                        aria-label={eng.label}
                        class="w-64 rounded-md border border-input bg-background px-2 py-1.5 text-sm"
                        disabled={busy === 'app'}
                        value={cur}
                        onchange={(e) => onEngineSelect(eng.key, (e.currentTarget as HTMLSelectElement).value, cur)}
                      >
                        {#each engineOptions(cur) as m (m)}
                          <option value={m}>{m}</option>
                        {/each}
                        <option value={CUSTOM}>Custom…</option>
                      </select>
                    {/if}
                  </div>
                </div>
              {/each}

              <Separator />

              <div class="flex flex-wrap items-center gap-3">
                <div class="min-w-[180px] flex-1">
                  <div class="text-sm font-medium">Max video reference images</div>
                  <div class="text-[11px] text-muted-foreground">
                    How many character / asset frames feed the video model.
                  </div>
                </div>
                <Input
                  type="number"
                  min="1"
                  max="10"
                  class="h-8 w-24 text-sm"
                  disabled={busy === 'app'}
                  value={app.max_video_refs}
                  onchange={(e) => {
                    const n = parseInt((e.currentTarget as HTMLInputElement).value, 10);
                    if (!Number.isNaN(n) && n !== app!.max_video_refs) saveApp({ max_video_refs: n });
                  }}
                />
              </div>
            {/if}
          </CardContent>
        </Card>
      </TabsContent>

      <!-- ============================================ DEFAULTS -->
      <TabsContent value="defaults">
        <Card>
          <CardHeader>
            <CardTitle class="text-base">Scene defaults</CardTitle>
            <CardDescription>Applied to new scenes and renders.</CardDescription>
          </CardHeader>
          <CardContent class="space-y-4">
            {#if app}
              <div class="flex flex-wrap items-center gap-3">
                <div class="min-w-[180px] flex-1 text-sm font-medium">Default aspect ratio</div>
                <select
                  aria-label="Default aspect ratio"
                  class="w-48 rounded-md border border-input bg-background px-2 py-1.5 text-sm"
                  disabled={busy === 'app'}
                  value={app.default_aspect_ratio}
                  onchange={(e) =>
                    saveApp({ default_aspect_ratio: (e.currentTarget as HTMLSelectElement).value })}
                >
                  {#each ASPECT_RATIOS as r (r)}
                    <option value={r}>{r}</option>
                  {/each}
                </select>
              </div>

              <div class="flex flex-wrap items-center gap-3">
                <div class="min-w-[180px] flex-1 text-sm font-medium">Default scene duration (s)</div>
                <Input
                  type="number"
                  min="0.5"
                  step="0.5"
                  class="h-8 w-24 text-sm"
                  disabled={busy === 'app'}
                  value={app.default_scene_duration}
                  onchange={(e) => {
                    const n = parseFloat((e.currentTarget as HTMLInputElement).value);
                    if (!Number.isNaN(n) && n !== app!.default_scene_duration)
                      saveApp({ default_scene_duration: n });
                  }}
                />
              </div>

              <div class="flex flex-wrap items-center gap-3">
                <div class="min-w-[180px] flex-1 text-sm font-medium">Dialogue language</div>
                <select
                  aria-label="Dialogue language"
                  class="w-48 rounded-md border border-input bg-background px-2 py-1.5 text-sm"
                  disabled={busy === 'app'}
                  value={app.dialogue_language}
                  onchange={(e) =>
                    saveApp({ dialogue_language: (e.currentTarget as HTMLSelectElement).value })}
                >
                  {#each DIALOGUE_LANGUAGES as l (l.value)}
                    <option value={l.value}>{l.label}</option>
                  {/each}
                </select>
              </div>
            {/if}
          </CardContent>
        </Card>

        <Card class="mt-4">
          <CardHeader>
            <CardTitle class="text-base">Captions</CardTitle>
            <CardDescription>Auto-caption style, language and transcription model.</CardDescription>
          </CardHeader>
          <CardContent class="space-y-4">
            {#if app}
              <div class="flex flex-wrap items-center gap-3">
                <div class="min-w-[180px] flex-1 text-sm font-medium">Caption style</div>
                <select
                  aria-label="Caption style"
                  class="w-48 rounded-md border border-input bg-background px-2 py-1.5 text-sm"
                  disabled={busy === 'app'}
                  value={app.caption_style}
                  onchange={(e) =>
                    saveApp({ caption_style: (e.currentTarget as HTMLSelectElement).value })}
                >
                  {#each CAPTION_STYLES as s (s)}
                    <option value={s}>{s}</option>
                  {/each}
                </select>
              </div>

              <div class="flex flex-wrap items-center gap-3">
                <div class="min-w-[180px] flex-1 text-sm font-medium">Caption language</div>
                <select
                  aria-label="Caption language"
                  class="w-48 rounded-md border border-input bg-background px-2 py-1.5 text-sm"
                  disabled={busy === 'app'}
                  value={app.caption_language}
                  onchange={(e) =>
                    saveApp({ caption_language: (e.currentTarget as HTMLSelectElement).value })}
                >
                  {#each CAPTION_LANGUAGES as l (l.value)}
                    <option value={l.value}>{l.label}</option>
                  {/each}
                </select>
              </div>

              <div class="flex flex-wrap items-center gap-3">
                <div class="min-w-[180px] flex-1 text-sm font-medium">Whisper model</div>
                <select
                  aria-label="Whisper model"
                  class="w-48 rounded-md border border-input bg-background px-2 py-1.5 text-sm"
                  disabled={busy === 'app'}
                  value={app.whisper_model}
                  onchange={(e) =>
                    saveApp({ whisper_model: (e.currentTarget as HTMLSelectElement).value })}
                >
                  {#each WHISPER_MODELS as m (m)}
                    <option value={m}>{m}</option>
                  {/each}
                </select>
              </div>
            {/if}
          </CardContent>
        </Card>

        <Card class="mt-4">
          <CardHeader>
            <CardTitle class="text-base">Render negative prompts</CardTitle>
            <CardDescription>
              Fragments appended to every render to steer the model away from common artefacts.
            </CardDescription>
          </CardHeader>
          <CardContent class="space-y-3">
            {#if app}
              {#if app.render_negatives.length}
                <div class="flex flex-wrap gap-2">
                  {#each app.render_negatives as neg, i (neg)}
                    <span
                      class="inline-flex items-center gap-1 rounded-md border border-border bg-muted/40 px-2 py-1 text-xs"
                    >
                      {neg}
                      <button
                        type="button"
                        class="text-muted-foreground hover:text-destructive disabled:opacity-40"
                        title="Remove"
                        aria-label="Remove {neg}"
                        disabled={busy === 'app'}
                        onclick={() => removeNegative(i)}
                      >
                        <Trash2 class="size-3" />
                      </button>
                    </span>
                  {/each}
                </div>
              {:else}
                <p class="text-xs text-muted-foreground">No negative prompts yet.</p>
              {/if}
              <form
                class="flex items-center gap-2"
                onsubmit={(e) => {
                  e.preventDefault();
                  addNegative();
                }}
              >
                <Input
                  class="h-8 max-w-xs text-sm"
                  placeholder="e.g. blurry, extra fingers"
                  bind:value={newNegative}
                  disabled={busy === 'app'}
                />
                <Button type="submit" size="sm" variant="outline" disabled={busy === 'app' || !newNegative.trim()}>
                  <Plus class="size-3.5 mr-1" />Add
                </Button>
              </form>
            {/if}
          </CardContent>
        </Card>
      </TabsContent>

      <!-- ============================================ AGENTS -->
      <TabsContent value="agents">
        <Card>
          <CardHeader>
            <CardTitle class="text-base">Agent routing</CardTitle>
            <CardDescription>
              Choose which provider and model powers each step. Only configured providers are
              selectable; model ids can be free-typed.
            </CardDescription>
          </CardHeader>
          <CardContent>
           <div class="space-y-5">
            <!-- Bulk controls -->
            <div class="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-muted/30 p-3">
              <span class="text-xs font-medium">Set all text agents to</span>
              <select
                aria-label="Bulk provider for text agents"
                class="rounded-md border border-input bg-background px-2 py-1.5 text-sm"
                bind:value={bulkTextProvider}
                disabled={!!busy}
              >
                <option value="">Choose provider…</option>
                {#each configuredProviders as p (p.name)}
                  <option value={p.name}>{providerLabels[p.name] ?? p.name}</option>
                {/each}
              </select>
              <Button
                size="sm"
                variant="secondary"
                disabled={!!busy || !bulkTextProvider}
                onclick={() => setAllText(bulkTextProvider)}
              >
                {busy === 'bulk-text' ? 'Applying…' : 'Apply'}
              </Button>
              <div class="flex-1"></div>
              <Button size="sm" variant="ghost" disabled={!!busy} onclick={resetAllAgents}>
                <RotateCcw class="size-3.5 mr-1" />
                {busy === 'bulk-reset' ? 'Resetting…' : 'Reset all'}
              </Button>
            </div>

            {#snippet agentRow(a: Agent)}
              <div
                class="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-card p-3"
                data-agent={a.agent}
              >
                <div class="min-w-[160px] flex-1">
                  <div class="flex items-center gap-2">
                    <span class="text-sm font-medium" title={agentDesc[a.agent] ?? ''}>{a.label}</span>
                    {#if isDefault(a)}
                      <Badge variant="outline" class="text-[10px]">default</Badge>
                    {/if}
                  </div>
                  <div class="text-[11px] text-muted-foreground">
                    {agentDesc[a.agent] ?? ''}
                    {#if !isDefault(a)}
                      <span class="block">
                        default: {providerLabels[a.default_provider] ?? a.default_provider} / {a.default_model}
                      </span>
                    {/if}
                  </div>
                </div>

                <div class="flex items-center gap-2">
                  <select
                    aria-label="{a.label} provider"
                    class="rounded-md border border-input bg-background px-2 py-1.5 text-sm"
                    disabled={busy === `agent-${a.agent}` || !!busy}
                    value={a.provider}
                    onchange={(e) => onAgentProvider(a, (e.currentTarget as HTMLSelectElement).value)}
                  >
                    {#each configuredProviders as p (p.name)}
                      <option value={p.name}>{providerLabels[p.name] ?? p.name}</option>
                    {/each}
                    {#if !byName[a.provider]?.configured}
                      <option value={a.provider}>{providerLabels[a.provider] ?? a.provider} (unconfigured)</option>
                    {/if}
                  </select>

                  {#if agentCustomOpen[a.agent]}
                    <Input
                      class="h-8 w-48 text-sm"
                      placeholder="Custom model id"
                      bind:value={agentCustomVal[a.agent]}
                      onkeydown={(e) => e.key === 'Enter' && commitAgentCustom(a)}
                    />
                    <Button size="sm" disabled={busy === `agent-${a.agent}`} onclick={() => commitAgentCustom(a)}>
                      Save
                    </Button>
                    <Button size="sm" variant="ghost" onclick={() => (agentCustomOpen[a.agent] = false)}>
                      Cancel
                    </Button>
                  {:else}
                    <select
                      aria-label="{a.label} model"
                      class="w-48 rounded-md border border-input bg-background px-2 py-1.5 text-sm"
                      disabled={busy === `agent-${a.agent}` || !!busy}
                      value={a.model}
                      onchange={(e) => onAgentModelSelect(a, (e.currentTarget as HTMLSelectElement).value)}
                    >
                      {#if !suggestedFor(a.provider).includes(a.model)}
                        <option value={a.model}>{a.model}</option>
                      {/if}
                      {#each suggestedFor(a.provider) as m (m)}
                        <option value={m}>{m}</option>
                      {/each}
                      <option value={CUSTOM}>Custom…</option>
                    </select>

                    <button
                      type="button"
                      title="Reset to default"
                      aria-label="Reset {a.label} to default"
                      class="rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-40"
                      disabled={busy === `agent-${a.agent}` || isDefault(a)}
                      onclick={() => resetAgent(a)}
                    >
                      <RotateCcw class="size-4" />
                    </button>
                  {/if}
                </div>
              </div>
            {/snippet}

            <div>
              <div class="mb-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
                Text agents
              </div>
              <div class="space-y-2">
                {#each textAgents as a (a.agent)}
                  {@render agentRow(a)}
                {/each}
              </div>
            </div>

            <div>
              <div class="mb-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
                Vision agents
              </div>
              <div class="space-y-2">
                {#each visionAgents as a (a.agent)}
                  {@render agentRow(a)}
                {/each}
              </div>
            </div>
           </div>
          </CardContent>
        </Card>
      </TabsContent>

      <!-- ============================================ APPEARANCE -->
      <TabsContent value="appearance">
        <Card>
          <CardHeader>
            <CardTitle class="flex items-center gap-2 text-base">
              <Palette class="size-4" />Appearance
            </CardTitle>
            <CardDescription>Choose how VideoFlow looks. Stored on this device.</CardDescription>
          </CardHeader>
          <CardContent>
            <div role="radiogroup" aria-label="Theme" class="flex flex-wrap gap-2">
              {#each [{ v: 'light', label: 'Light', icon: Sun }, { v: 'dark', label: 'Dark', icon: Moon }, { v: 'system', label: 'System', icon: Monitor }] as opt (opt.v)}
                <button
                  type="button"
                  role="radio"
                  aria-checked={theme === opt.v}
                  class="flex items-center gap-2 rounded-lg border px-4 py-2 text-sm transition-colors
                         {theme === opt.v
                    ? 'border-primary bg-accent font-medium'
                    : 'border-border hover:bg-accent/50'}"
                  onclick={() => setTheme(opt.v as 'light' | 'dark' | 'system')}
                >
                  <opt.icon class="size-4" />
                  {opt.label}
                </button>
              {/each}
            </div>
          </CardContent>
        </Card>
      </TabsContent>
    </Tabs>
  {/if}
</div>
