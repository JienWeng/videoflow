<script lang="ts">
  import { del, get, post } from '$lib/api';
  import { runBackgroundOp, type Op } from '$lib/ops';
  import { Suggestion, Suggestions } from '$lib/components/ai-elements/suggestion';
  import { Badge } from '$lib/components/ui/badge';
  import { Button } from '$lib/components/ui/button';
  import * as Card from '$lib/components/ui/card';
  import { Textarea } from '$lib/components/ui/textarea';
  import Lightbulb from '@lucide/svelte/icons/lightbulb';
  import LoaderCircle from '@lucide/svelte/icons/loader-circle';
  import Play from '@lucide/svelte/icons/play';
  import Trash2 from '@lucide/svelte/icons/trash-2';
  import { toast } from 'svelte-sonner';

  interface Option {
    id: string;
    title?: string;
    name?: string;
    video?: string | null;
  }

  interface Intent {
    action: string;
    scene_id?: string | null;
    character_id?: string | null;
    shot_id?: string | null;
    output_id?: string | null;
    style?: string | null;
    language?: string | null;
    idea?: string | null;
    scene_count?: number | null;
    confidence?: number;
    reply?: string;
  }

  interface Options {
    scenes: Option[];
    characters: Option[];
    outputs: Option[];
    caption_styles: string[];
  }

  interface IdeaOption {
    title: string;
    premise: string;
    hook: string;
    why_it_works: string;
  }

  interface IdeaOptions {
    options: IdeaOption[];
    recommended_index: number;
    reasoning: string;
  }

  let {
    intent,
    options,
    onran,
    onfocus,
    onsuggest
  }: {
    intent: Intent;
    options: Options;
    onran?: (result: any) => void | Promise<void>;
    onfocus?: (id: string) => void;
    onsuggest?: (text: string) => void;
  } = $props();

  // Each card gets one fixed intent, so plain init from props is fine.
  let busy = $state(false);
  // svelte-ignore state_referenced_locally
  let idea = $state(intent.idea ?? '');
  // svelte-ignore state_referenced_locally
  let sceneCount = $state<number | ''>(intent.scene_count ?? '');
  // svelte-ignore state_referenced_locally
  let sceneId = $state(intent.scene_id ?? '');
  // svelte-ignore state_referenced_locally
  let shotId = $state(intent.shot_id ?? '');
  // svelte-ignore state_referenced_locally
  let outputId = $state(intent.output_id ?? '');
  // svelte-ignore state_referenced_locally
  let captionStyle = $state(intent.style ?? 'kids');
  let captionModel = $state('');
  // svelte-ignore state_referenced_locally
  let captionLanguage = $state(intent.language ?? 'zh');
  let shots = $state<{ id: string; shot_order: number; prompt: string }[]>([]);
  let captionModels = $state<string[]>([]);
  let maxAssets = $state(4);
  let autoAssets = $state(true);
  let plannedAssets = $state<
    { name: string; asset_type: string; shot_orders: number[] }[] | null
  >(null);
  // Ideation phase for generate_script: null = phase 1 (raw idea),
  // set = phase 2 (pick one of the developed concepts).
  let ideaOptions = $state<IdeaOptions | null>(null);
  let selectedIdea = $state(0);
  let developing = $state(false);

  const labels: Record<string, string> = {
    generate_script: 'Generate script',
    generate_scenes: 'Expand scene',
    generate_shots: 'Generate shots',
    storyboard: 'Generate storyboard',
    render_scene: 'Render scene',
    render_shot: 'Render shot',
    caption: 'Add captions',
    retry_render: 'Fix & re-render',
    generate_assets: 'Generate assets',
    refine_scene: 'AI refine scene',
    refine_shot: 'AI refine shot',
    delete_scene: 'Delete scene',
    style_ingest: 'Ingest style from story',
    plan_assets: 'Suggest assets'
  };

  const needsShot = (action: string) => action === 'render_shot' || action === 'refine_shot';

  async function loadShots() {
    shotId = intent.shot_id && sceneId === intent.scene_id ? intent.shot_id : '';
    shots = [];
    if (!sceneId) return;
    try {
      shots = await get(`/scenes/${sceneId}/shots`);
      if (shotId && !shots.some((s) => s.id === shotId)) shotId = '';
    } catch (e) {
      toast.error(`Failed to load shots: ${(e as Error).message}`);
    }
  }

  // svelte-ignore state_referenced_locally
  if (needsShot(intent.action) && sceneId) loadShots();

  // svelte-ignore state_referenced_locally
  if (intent.action === 'caption') {
    get('/caption-config')
      .then((cfg) => {
        captionModels = cfg.models ?? [];
        captionModel = cfg.default_model ?? captionModels[0] ?? '';
        if (!intent.language) captionLanguage = cfg.default_language ?? 'zh';
        if (!intent.style && cfg.default_style) captionStyle = cfg.default_style;
      })
      .catch(() => {});
  }

  const ready = $derived.by(() => {
    switch (intent.action) {
      case 'generate_script':
        return idea.trim().length > 0;
      case 'generate_scenes':
      case 'generate_shots':
      case 'storyboard':
      case 'render_scene':
      case 'generate_assets':
      case 'delete_scene':
      case 'plan_assets':
        return !!sceneId;
      case 'refine_scene':
        return !!sceneId && idea.trim().length > 0;
      case 'render_shot':
        return !!sceneId && !!shotId;
      case 'refine_shot':
        return !!sceneId && !!shotId && idea.trim().length > 0;
      case 'style_ingest':
        return true;
      case 'caption':
        return !!outputId && !!captionStyle;
      case 'retry_render':
        return !!outputId;
      default:
        return false;
    }
  });

  function videoLabel(o: Option): string {
    const file = o.video?.split('/').pop();
    return file ?? o.id;
  }

  /** Phase 1 -> 2: develop the raw idea into two mature concept options. */
  async function developIdeas() {
    developing = true;
    try {
      const result: IdeaOptions = await post('/ideas/develop', { idea: idea.trim() });
      ideaOptions = result;
      selectedIdea = result.recommended_index ?? 0;
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      developing = false;
    }
  }

  /** Compose the chosen concept into the idea passed to script generation. */
  function composedIdea(): string {
    const o = ideaOptions?.options[selectedIdea];
    if (!o) return idea.trim();
    return [`${o.title} — ${o.premise}`, o.hook].filter(Boolean).join(' ').trim();
  }

  /** Long generations run as background ops: busy holds until the op is terminal. */
  async function runInBackground(
    path: string,
    body: unknown,
    label: string,
    focus: (op: Op) => string | undefined
  ) {
    busy = true;
    try {
      await runBackgroundOp(path, body, {
        label,
        onDone: async (op) => {
          busy = false;
          await onran?.(op.result_json ?? op); // let the canvas refresh before zooming to the new node
          const focusId = focus(op);
          if (focusId) onfocus?.(focusId);
        },
        onFail: () => (busy = false)
      });
    } catch (e) {
      busy = false;
      toast.error((e as Error).message);
    }
  }

  async function run() {
    switch (intent.action) {
      case 'storyboard':
        return runInBackground(
          `/scenes/${sceneId}/storyboard`,
          undefined,
          'Storyboard',
          (op) => op.result_json?.asset_id ?? op.scene_id ?? sceneId
        );
      case 'generate_shots':
        return runInBackground(
          `/scenes/${sceneId}/shots/generate`,
          { auto_assets: autoAssets },
          'Shot generation',
          (op) => op.result_json?.scene_id ?? op.scene_id ?? sceneId
        );
      case 'generate_assets':
        return runInBackground(
          `/scenes/${sceneId}/assets/generate`,
          { instruction: idea.trim(), max_assets: maxAssets },
          'Asset generation',
          (op) => op.result_json?.asset_ids?.[0]
        );
      case 'caption':
        return runInBackground(
          `/outputs/${outputId}/caption`,
          {
            style: captionStyle,
            model: captionModel || null,
            language: captionLanguage === 'auto' ? null : captionLanguage
          },
          'Captioning',
          (op) => op.result_json?.output_id ?? op.output_id ?? outputId
        );
    }
    busy = true;
    try {
      let result: any;
      let focusId: string | undefined;
      switch (intent.action) {
        case 'generate_script':
          result = await post('/scripts/generate', {
            idea: ideaOptions ? composedIdea() : idea.trim(),
            ...(sceneCount ? { scene_count: sceneCount } : {})
          });
          focusId = result.scenes?.at(-1)?.id;
          toast.success(`Script generated — ${result.scenes?.length ?? 0} scenes`);
          break;
        case 'generate_scenes':
          result = await post(`/scenes/${sceneId}/generate`, { character_ids: [] });
          focusId = result.id ?? sceneId;
          toast.success('Scene expanded');
          break;
        case 'render_scene':
          result = await post(`/scenes/${sceneId}/render`);
          focusId = result.job_id;
          toast.success(`Render started — job ${result.job_id}`);
          break;
        case 'render_shot':
          result = await post('/render/from-shot', { scene_id: sceneId, shot_id: shotId });
          focusId = result.job_id;
          toast.success(`Render started — job ${result.job_id}`);
          break;
        case 'refine_scene':
          result = await post(`/scenes/${sceneId}/refine`, { instruction: idea.trim() });
          focusId = sceneId;
          toast.success(result.note || 'Scene refined');
          break;
        case 'refine_shot':
          result = await post(`/shots/${shotId}/refine`, { instruction: idea.trim() });
          focusId = shotId;
          toast.success(result.note || 'Shot refined');
          break;
        case 'delete_scene':
          result = await del(`/scenes/${sceneId}`);
          toast.success(`Scene deleted — ${result.shots_deleted ?? 0} shots removed`);
          break;
        case 'style_ingest':
          result = await post('/style/ingest');
          toast.success('Style updated');
          break;
        case 'plan_assets':
          result = await post(`/scenes/${sceneId}/assets/plan`, {
            instruction: idea.trim(),
            max_assets: maxAssets
          });
          plannedAssets = result.assets ?? [];
          focusId = sceneId;
          toast.success(`${result.assets?.length ?? 0} asset suggestions`);
          break;
        case 'retry_render':
          result = await post(`/outputs/${outputId}/retry`);
          focusId = result.job_id;
          toast.success(`Corrective re-render started — job ${result.job_id}`);
          break;
      }
      await onran?.(result); // let the canvas refresh before zooming to the new node
      if (focusId) onfocus?.(focusId);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      busy = false;
    }
  }

  const selectClass =
    'w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm';
  const labelClass = 'block text-xs text-muted-foreground mb-1';
</script>

<Card.Root class="mt-2 max-w-sm gap-3 py-4">
  <Card.Content class="space-y-3 px-4">
    {#if intent.action === 'unknown'}
      <div class="text-sm text-muted-foreground space-y-1">
        <p class="font-medium text-foreground">I can:</p>
        <ul class="list-disc pl-4 space-y-0.5">
          <li>generate a script from an idea</li>
          <li>expand a scene / generate shots</li>
          <li>create a storyboard (分镜图)</li>
          <li>render a scene or a single shot</li>
          <li>add captions to a rendered video</li>
          <li>fix &amp; re-render a video using its QA review feedback</li>
          <li>generate props/assets for a scene (生成场景道具)</li>
          <li>refine a scene or shot with AI (帮我改一下场景)</li>
          <li>delete a scene (with confirmation)</li>
          <li>derive the project style from the story</li>
          <li>suggest assets without generating them</li>
        </ul>
      </div>
      <Suggestions>
        {#each ['生成分镜图', 'Render scene', 'Add captions', 'Generate a script', '生成场景道具', '帮我改一下场景', 'Suggest assets'] as s (s)}
          <Suggestion suggestion={s} onclick={(text) => onsuggest?.(text)} />
        {/each}
      </Suggestions>
    {:else}
      {#if intent.action === 'generate_script'}
        {#if !ideaOptions}
          <div>
            <label class={labelClass} for="idea-{intent.action}">Idea</label>
            <Textarea id="idea-{intent.action}" bind:value={idea} rows={3} placeholder="Describe the video idea…" />
          </div>
        {:else}
          <div class="space-y-2">
            {#each ideaOptions.options as o, i (i)}
              <button
                type="button"
                class="w-full rounded-md border p-2.5 text-left text-sm transition-colors {selectedIdea === i
                  ? 'border-primary bg-primary/5'
                  : 'border-input hover:border-muted-foreground/40'}"
                onclick={() => (selectedIdea = i)}
              >
                <div class="flex items-center gap-1.5 flex-wrap">
                  <span class="font-bold">{o.title}</span>
                  {#if i === ideaOptions.recommended_index}
                    <Badge class="px-1.5 py-0 text-[10px]">Recommended</Badge>
                  {/if}
                </div>
                <p class="mt-0.5">{o.premise}</p>
                {#if o.hook}<p class="mt-0.5 text-muted-foreground">{o.hook}</p>{/if}
                {#if o.why_it_works}
                  <p class="mt-0.5 italic text-muted-foreground">{o.why_it_works}</p>
                {/if}
              </button>
            {/each}
            {#if ideaOptions.reasoning}
              <p class="text-xs text-muted-foreground">{ideaOptions.reasoning}</p>
            {/if}
          </div>
        {/if}
        <div>
          <label class={labelClass} for="scenes-{intent.action}">Scenes (optional)</label>
          <input id="scenes-{intent.action}" type="number" min="1" max="20"
            bind:value={sceneCount} placeholder="auto" class={selectClass} />
          <p class="text-xs text-muted-foreground mt-1">1 scene = 1 video</p>
        </div>
      {/if}

      {#if ['generate_scenes', 'generate_shots', 'storyboard', 'render_scene', 'render_shot', 'generate_assets', 'refine_scene', 'refine_shot', 'delete_scene', 'plan_assets'].includes(intent.action)}
        <div>
          <label class={labelClass} for="scene-{intent.action}">Scene</label>
          <select
            id="scene-{intent.action}"
            bind:value={sceneId}
            onchange={() => needsShot(intent.action) && loadShots()}
            class={selectClass}
          >
            <option value="">choose…</option>
            {#each options.scenes as s (s.id)}<option value={s.id}>{s.title}</option>{/each}
          </select>
        </div>
      {/if}

      {#if needsShot(intent.action)}
        <div>
          <label class={labelClass} for="shot-{intent.action}">Shot</label>
          <select id="shot-{intent.action}" bind:value={shotId} disabled={!shots.length} class={selectClass}>
            <option value="">choose…</option>
            {#each shots as sh (sh.id)}
              <option value={sh.id}>#{sh.shot_order + 1} {sh.prompt.slice(0, 50)}</option>
            {/each}
          </select>
        </div>
      {/if}

      {#if intent.action === 'generate_shots'}
        <label class="inline-flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer select-none">
          <input type="checkbox" class="w-auto" bind:checked={autoAssets} />
          auto props
        </label>
      {/if}

      {#if ['refine_scene', 'refine_shot'].includes(intent.action)}
        <div>
          <label class={labelClass} for="instr-{intent.action}">Instruction</label>
          <Textarea id="instr-{intent.action}" bind:value={idea} rows={2}
            placeholder="e.g. make the lighting warmer / 台词更简单" />
        </div>
      {/if}

      {#if intent.action === 'delete_scene'}
        <p class="text-xs text-destructive">
          Deletes the scene and its shots; renders are kept.
        </p>
      {/if}

      {#if intent.action === 'style_ingest'}
        <p class="text-xs text-muted-foreground">
          Derives style_prompt/palette/lighting/audience/tone from your story (keeps name + pinned references).
        </p>
      {/if}

      {#if ['generate_assets', 'plan_assets'].includes(intent.action)}
        <div>
          <label class={labelClass} for="instr-{intent.action}">Instruction (optional)</label>
          <Textarea id="instr-{intent.action}" bind:value={idea} rows={2}
            placeholder="e.g. 需要一个红色杯子 / a red cup" />
        </div>
        <div>
          <label class={labelClass} for="max-{intent.action}">Max assets</label>
          <input id="max-{intent.action}" type="number" min="1" max="8"
            bind:value={maxAssets} class={selectClass} />
        </div>
      {/if}

      {#if intent.action === 'plan_assets' && plannedAssets}
        <div class="text-xs space-y-1">
          {#if plannedAssets.length === 0}
            <p class="text-muted-foreground">No missing assets — the scene is covered.</p>
          {:else}
            <ul class="list-disc pl-4 space-y-0.5">
              {#each plannedAssets as a (a.name)}
                <li>
                  <span class="font-medium">{a.name}</span>
                  <span class="text-muted-foreground">
                    ({a.asset_type}{a.shot_orders?.length
                      ? `, shots ${a.shot_orders.map((o) => o + 1).join(', ')}`
                      : ''})
                  </span>
                </li>
              {/each}
            </ul>
            <p class="text-muted-foreground">
              Generate them on the Scenes page or say '生成场景道具'.
            </p>
          {/if}
        </div>
      {/if}

      {#if ['caption', 'retry_render'].includes(intent.action)}
        <div>
          <label class={labelClass} for="output-{intent.action}">Output</label>
          <select id="output-{intent.action}" bind:value={outputId} class={selectClass}>
            <option value="">choose…</option>
            {#each options.outputs as o (o.id)}<option value={o.id}>{videoLabel(o)}</option>{/each}
          </select>
        </div>
      {/if}

      {#if intent.action === 'caption'}
        <div class="grid grid-cols-3 gap-2">
          <div>
            <label class={labelClass} for="style-{intent.action}">Style</label>
            <select id="style-{intent.action}" bind:value={captionStyle} class={selectClass}>
              {#each options.caption_styles as st (st)}<option value={st}>{st}</option>{/each}
            </select>
          </div>
          <div>
            <label class={labelClass} for="model-{intent.action}">Model</label>
            <select id="model-{intent.action}" bind:value={captionModel} class={selectClass}>
              {#each captionModels as m (m)}<option value={m}>{m}</option>{/each}
            </select>
          </div>
          <div>
            <label class={labelClass} for="lang-{intent.action}">Language</label>
            <select id="lang-{intent.action}" bind:value={captionLanguage} class={selectClass}>
              <option value="zh">zh</option>
              <option value="en">en</option>
              <option value="auto">auto</option>
            </select>
          </div>
        </div>
      {/if}

      <div class="flex items-center gap-1.5 pt-1">
        {#if intent.action === 'generate_script' && !ideaOptions}
          <Button
            size="sm"
            class="rounded-full px-4"
            disabled={busy || developing || !ready}
            onclick={developIdeas}
          >
            {#if developing}
              <LoaderCircle class="size-4 mr-1 animate-spin" />
            {:else}
              <Lightbulb class="size-4 mr-1" />
            {/if}
            {developing ? 'Developing…' : 'Develop ideas'}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            class="rounded-full px-3"
            disabled={busy || developing || !ready}
            onclick={run}
          >
            {#if busy}<LoaderCircle class="size-4 mr-1 animate-spin" />{/if}
            {busy ? 'Running…' : 'Skip — generate directly'}
          </Button>
        {:else if intent.action === 'generate_script'}
          <Button size="sm" class="rounded-full px-4" disabled={busy} onclick={run}>
            {#if busy}
              <LoaderCircle class="size-4 mr-1 animate-spin" />
            {:else}
              <Play class="size-4 mr-1" />
            {/if}
            {busy ? 'Running…' : 'Generate script'}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            class="rounded-full px-3"
            disabled={busy}
            onclick={() => (ideaOptions = null)}
          >
            Back
          </Button>
        {:else}
          <Button
            size="sm"
            variant={intent.action === 'delete_scene' ? 'destructive' : 'default'}
            class="rounded-full px-4"
            disabled={busy || !ready}
            onclick={run}
          >
            {#if busy}
              <LoaderCircle class="size-4 mr-1 animate-spin" />
            {:else if intent.action === 'delete_scene'}
              <Trash2 class="size-4 mr-1" />
            {:else}
              <Play class="size-4 mr-1" />
            {/if}
            {busy ? 'Running…' : (labels[intent.action] ?? 'Run')}
          </Button>
        {/if}
      </div>
    {/if}
  </Card.Content>
</Card.Root>
