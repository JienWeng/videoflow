<script lang="ts">
  import { onMount } from 'svelte';
  import { get, put } from '$lib/api';
  import { Card, CardContent } from '$lib/components/ui/card';
  import { Badge } from '$lib/components/ui/badge';
  import { Skeleton } from '$lib/components/ui/skeleton';
  import { toast } from 'svelte-sonner';
  import { RotateCcw, TriangleAlert } from '@lucide/svelte';

  type Agent = {
    agent: string;
    label: string;
    provider: string;
    model: string;
    default_provider: string;
    default_model: string;
  };
  type Provider = { name: string; configured: boolean; models: string[]; default_model: string };

  let agents: Agent[] = $state([]);
  let providers: Provider[] = $state([]);
  let loaded = $state(false);
  let error = $state('');
  let busy = $state('');

  const providerLabels: Record<string, string> = {
    minimax: 'MiniMax',
    openai: 'OpenAI',
    anthropic: 'Anthropic',
    gemini: 'Gemini',
    atlas: 'AtlasCloud'
  };

  const byName = $derived(Object.fromEntries(providers.map((p) => [p.name, p])));
  const configuredProviders = $derived(providers.filter((p) => p.configured));
  const unconfigured = $derived(providers.filter((p) => !p.configured));

  async function refresh() {
    [agents, providers] = await Promise.all([get('/settings/agents'), get('/settings/providers')]);
  }
  onMount(() =>
    refresh()
      .catch((e) => (error = e.message))
      .finally(() => (loaded = true))
  );

  function modelsFor(provider: string): string[] {
    return byName[provider]?.models ?? [];
  }

  function isDefault(a: Agent): boolean {
    return a.provider === a.default_provider && a.model === a.default_model;
  }

  async function save(a: Agent, provider: string, model: string) {
    busy = a.agent;
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

  async function onProvider(a: Agent, provider: string) {
    if (provider === a.provider) return;
    // Pick the new provider's first model (or its default) as the model.
    const models = modelsFor(provider);
    const model = byName[provider]?.default_model ?? models[0];
    if (!model) {
      toast.error('No models available for this provider');
      return;
    }
    await save(a, provider, model);
  }

  async function onModel(a: Agent, model: string) {
    if (model === a.model) return;
    await save(a, a.provider, model);
  }

  async function reset(a: Agent) {
    busy = a.agent;
    try {
      const updated = await put(`/settings/agents/${a.agent}`, { provider: null, model: null });
      agents = agents.map((x) => (x.agent === a.agent ? updated : x));
      toast.success(`${a.label} reset to default`);
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      busy = '';
    }
  }
</script>

<div class="p-6 max-w-3xl">
  <div class="mb-4">
    <h1 class="text-lg font-semibold">Settings</h1>
    <p class="text-sm text-muted-foreground">
      Choose which AI model powers each step. Only configured providers are selectable.
    </p>
  </div>

  {#if error}
    <Card class="mb-4 border-destructive/40">
      <CardContent class="p-4 text-sm text-destructive">{error}</CardContent>
    </Card>
  {/if}

  {#if loaded && unconfigured.length}
    <Card class="mb-4 border-amber-500/40">
      <CardContent class="p-3 flex items-start gap-2 text-sm">
        <TriangleAlert class="size-4 mt-0.5 shrink-0 text-amber-500" />
        <div>
          <span class="font-medium">Some providers aren't configured</span>
          <span class="text-muted-foreground">
            — add an API key to enable:
            {unconfigured.map((p) => providerLabels[p.name] ?? p.name).join(', ')}.
          </span>
        </div>
      </CardContent>
    </Card>
  {/if}

  {#if !loaded}
    <div class="space-y-2">
      {#each Array(6) as _}
        <Skeleton class="h-16 w-full" />
      {/each}
    </div>
  {:else}
    <div class="space-y-2">
      {#each agents as a (a.agent)}
        <div
          class="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-card p-3"
          data-agent={a.agent}
        >
          <div class="min-w-[140px] flex-1">
            <div class="flex items-center gap-2">
              <span class="text-sm font-medium">{a.label}</span>
              {#if isDefault(a)}
                <Badge variant="outline" class="text-[10px]">default</Badge>
              {/if}
            </div>
            {#if !isDefault(a)}
              <div class="text-[11px] text-muted-foreground">
                default: {providerLabels[a.default_provider] ?? a.default_provider} / {a.default_model}
              </div>
            {/if}
          </div>

          <div class="flex items-center gap-2">
            <select
              aria-label="{a.label} provider"
              class="rounded-md border border-input bg-background px-2 py-1.5 text-sm"
              disabled={busy === a.agent}
              value={a.provider}
              onchange={(e) => onProvider(a, (e.currentTarget as HTMLSelectElement).value)}
            >
              {#each configuredProviders as p}
                <option value={p.name}>{providerLabels[p.name] ?? p.name}</option>
              {/each}
            </select>

            <select
              aria-label="{a.label} model"
              class="rounded-md border border-input bg-background px-2 py-1.5 text-sm"
              disabled={busy === a.agent}
              value={a.model}
              onchange={(e) => onModel(a, (e.currentTarget as HTMLSelectElement).value)}
            >
              {#each modelsFor(a.provider) as m}
                <option value={m}>{m}</option>
              {/each}
            </select>

            <button
              type="button"
              title="Reset to default"
              aria-label="Reset {a.label} to default"
              class="rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-40"
              disabled={busy === a.agent || isDefault(a)}
              onclick={() => reset(a)}
            >
              <RotateCcw class="size-4" />
            </button>
          </div>
        </div>
      {/each}
    </div>
  {/if}
</div>
