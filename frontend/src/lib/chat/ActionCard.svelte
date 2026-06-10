<script lang="ts">
  import { get, post } from '$lib/api';
  import { Suggestion, Suggestions } from '$lib/components/ai-elements/suggestion';
  import { Button } from '$lib/components/ui/button';
  import * as Card from '$lib/components/ui/card';
  import { Textarea } from '$lib/components/ui/textarea';
  import LoaderCircle from '@lucide/svelte/icons/loader-circle';
  import Play from '@lucide/svelte/icons/play';
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

  const labels: Record<string, string> = {
    generate_script: 'Generate script',
    generate_scenes: 'Expand scene',
    generate_shots: 'Generate shots',
    storyboard: 'Generate storyboard',
    render_scene: 'Render scene',
    render_shot: 'Render shot',
    caption: 'Add captions',
    generate_assets: 'Generate assets'
  };

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
  if (intent.action === 'render_shot' && sceneId) loadShots();

  // svelte-ignore state_referenced_locally
  if (intent.action === 'caption') {
    get('/caption-config')
      .then((cfg) => {
        captionModels = cfg.models ?? [];
        captionModel = cfg.default_model ?? captionModels[0] ?? '';
        if (!intent.language) captionLanguage = cfg.default_language ?? 'zh';
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
        return !!sceneId;
      case 'render_shot':
        return !!sceneId && !!shotId;
      case 'caption':
        return !!outputId && !!captionStyle;
      default:
        return false;
    }
  });

  function videoLabel(o: Option): string {
    const file = o.video?.split('/').pop();
    return file ?? o.id;
  }

  async function run() {
    busy = true;
    try {
      let result: any;
      let focusId: string | undefined;
      switch (intent.action) {
        case 'generate_script':
          result = await post('/scripts/generate', {
            idea: idea.trim(),
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
        case 'generate_shots':
          result = await post(`/scenes/${sceneId}/shots/generate`, { auto_assets: autoAssets });
          focusId = sceneId;
          toast.success(`Shots generated (${Array.isArray(result) ? result.length : '?'})`);
          break;
        case 'storyboard':
          result = await post(`/scenes/${sceneId}/storyboard`);
          focusId = result.id ?? sceneId;
          toast.success('Storyboard generated');
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
        case 'generate_assets':
          result = await post(`/scenes/${sceneId}/assets/generate`, {
            instruction: idea.trim(),
            max_assets: maxAssets
          });
          focusId = Array.isArray(result) ? result[0]?.id : undefined;
          toast.success(`Generated ${Array.isArray(result) ? result.length : 0} assets`);
          break;
        case 'caption':
          result = await post(`/outputs/${outputId}/caption`, {
            style: captionStyle,
            model: captionModel || null,
            language: captionLanguage === 'auto' ? null : captionLanguage
          });
          focusId = result.id ?? outputId;
          toast.success('Captions added');
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
          <li>generate props/assets for a scene (生成场景道具)</li>
        </ul>
        <p>Scenes can be deleted from the Scenes page.</p>
      </div>
      <Suggestions>
        {#each ['生成分镜图', 'Render scene', 'Add captions', 'Generate a script', '生成场景道具'] as s (s)}
          <Suggestion suggestion={s} onclick={(text) => onsuggest?.(text)} />
        {/each}
      </Suggestions>
    {:else}
      {#if intent.action === 'generate_script'}
        <div>
          <label class={labelClass} for="idea-{intent.action}">Idea</label>
          <Textarea id="idea-{intent.action}" bind:value={idea} rows={3} placeholder="Describe the video idea…" />
        </div>
        <div>
          <label class={labelClass} for="scenes-{intent.action}">Scenes (optional)</label>
          <input id="scenes-{intent.action}" type="number" min="1" max="20"
            bind:value={sceneCount} placeholder="auto" class={selectClass} />
          <p class="text-xs text-muted-foreground mt-1">1 scene = 1 video</p>
        </div>
      {/if}

      {#if ['generate_scenes', 'generate_shots', 'storyboard', 'render_scene', 'render_shot', 'generate_assets'].includes(intent.action)}
        <div>
          <label class={labelClass} for="scene-{intent.action}">Scene</label>
          <select
            id="scene-{intent.action}"
            bind:value={sceneId}
            onchange={() => intent.action === 'render_shot' && loadShots()}
            class={selectClass}
          >
            <option value="">choose…</option>
            {#each options.scenes as s (s.id)}<option value={s.id}>{s.title}</option>{/each}
          </select>
        </div>
      {/if}

      {#if intent.action === 'render_shot'}
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

      {#if intent.action === 'generate_assets'}
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

      {#if intent.action === 'caption'}
        <div>
          <label class={labelClass} for="output-{intent.action}">Output</label>
          <select id="output-{intent.action}" bind:value={outputId} class={selectClass}>
            <option value="">choose…</option>
            {#each options.outputs as o (o.id)}<option value={o.id}>{videoLabel(o)}</option>{/each}
          </select>
        </div>
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
        <Button size="sm" class="rounded-full px-4" disabled={busy || !ready} onclick={run}>
          {#if busy}
            <LoaderCircle class="size-4 mr-1 animate-spin" />
          {:else}
            <Play class="size-4 mr-1" />
          {/if}
          {busy ? 'Running…' : (labels[intent.action] ?? 'Run')}
        </Button>
      </div>
    {/if}
  </Card.Content>
</Card.Root>
