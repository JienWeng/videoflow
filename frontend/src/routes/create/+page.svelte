<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { Clapperboard, Sparkles } from '@lucide/svelte';
  import { Button } from '$lib/components/ui/button';
  import GenerationProgress from '$lib/create/GenerationProgress.svelte';
  import { get, post } from '$lib/api';

  let idea = $state('');
  let style = $state('2d-picture-book');
  let aspectRatio = $state('9:16');
  let duration = $state('');
  let language = $state('English');
  let conversationMode = $state('dialogue');
  let instruction = $state('');
  let busy = $state(false);
  let opId = $state('');
  let opStatus = $state('');
  let opError = $state('');
  let stages = $state<string[]>([]);
  let preflight: any = $state(null);
  let preflightError = $state('');
  let activeProject: any = $state(null);
  let lastResult: any = $state(null);
  let poller: ReturnType<typeof setInterval> | null = null;
  let renderPoller: ReturnType<typeof setInterval> | null = null;

  function stopPolling() {
    if (poller) clearInterval(poller);
    poller = null;
  }

  function stopRenderPolling() {
    if (renderPoller) clearInterval(renderPoller);
    renderPoller = null;
  }

  async function checkRenderJobs() {
    const ids: string[] = lastResult?.render_job_ids ?? [];
    if (!ids.length) {
      busy = false;
      opStatus = 'completed';
      stopRenderPolling();
      return;
    }
    try {
      const jobs = await Promise.all(ids.map((id) => get(`/render-jobs/${id}`)));
      opError = '';
      const states = jobs.map((item) => item.job.status);
      if (states.some((state) => state === 'failed')) {
        opStatus = 'failed';
        opError = jobs.find((item) => item.job.status === 'failed')?.job.error || 'A render job failed.';
        busy = false;
        stopRenderPolling();
      } else if (states.every((state) => state === 'succeeded')) {
        opStatus = 'completed';
        busy = false;
        stopRenderPolling();
      } else {
        opStatus = 'rendering';
      }
    } catch (e: any) {
      opError = `Connection interrupted. Checking render status again… (${e.message})`;
    }
  }

  async function checkOperation() {
    if (!opId) return;
    try {
      const op = await get(`/ops/${opId}`);
      opError = '';
      opStatus = op.status;
      stages = op.result_json?.stages ?? stages;
      if (op.status === 'succeeded') {
        stopPolling();
        lastResult = op.result_json;
        opStatus = 'rendering';
        await checkRenderJobs();
        if (opStatus === 'rendering') renderPoller = setInterval(() => void checkRenderJobs(), 4000);
      } else if (op.status === 'failed') {
        stopPolling();
        opError = op.error || 'The generation failed.';
        busy = false;
      }
    } catch (e: any) {
      // Keep the last known state while the interval retries after reconnect.
      opError = `Connection interrupted. The operation is still running; reconnecting… (${e.message})`;
    }
  }

  async function loadPreflight(ratio: string, styleChoice: string) {
    preflightError = '';
    try {
      const params = new URLSearchParams({ aspect_ratio: ratio });
      params.set('style', styleChoice);
      preflight = await get(`/videos/preflight?${params}`);
      return preflight;
    } catch (e: any) {
      preflightError = e.message;
      preflight = null;
      return null;
    }
  }

  async function restoreOperation() {
    try {
      activeProject = await get('/projects/active');
      const ops = await get(`/ops?project_id=${encodeURIComponent(activeProject.id)}&kind=video_generation&limit=1`);
      const op = ops?.[0];
      if (!op) return;
      opId = op.id;
      opStatus = op.status;
      stages = op.result_json?.stages ?? [];
      lastResult = op.result_json;
      if (op.status === 'running') {
        busy = true;
        poller = setInterval(() => void checkOperation(), 2500);
        await checkOperation();
      } else if (op.status === 'succeeded') {
        opStatus = 'rendering';
        busy = true;
        await checkRenderJobs();
        if (opStatus === 'rendering') renderPoller = setInterval(() => void checkRenderJobs(), 4000);
      } else if (op.status === 'failed') {
        opError = op.error || 'The generation failed.';
      }
    } catch { /* Create remains usable if project history is unavailable. */ }
  }

  onMount(() => { void restoreOperation(); });

  $effect(() => {
    const ratio = aspectRatio;
    const styleChoice = style;
    void loadPreflight(ratio, styleChoice);
  });

  async function createVideo(e: SubmitEvent) {
    e.preventDefault();
    if (!idea.trim() || busy) return;
    busy = true;
    opError = '';
    stages = [];
    lastResult = null;
    await loadPreflight(aspectRatio, style);
    if (preflightError || preflight?.ready === false) {
      busy = false;
      return;
    }
    try {
      const response = await post('/videos/generate?background=true', {
        idea: idea.trim(),
        style,
        aspect_ratio: aspectRatio,
        language,
        conversation_mode: conversationMode,
        ...(duration ? { target_duration: Number(duration) } : {}),
        ...(instruction.trim() ? { instruction: instruction.trim() } : {})
      });
      opId = response.op_id;
      opStatus = response.status;
      activeProject = activeProject ?? await get('/projects/active');
      poller = setInterval(() => void checkOperation(), 2500);
      await checkOperation();
    } catch (e: any) {
      busy = false;
      opError = e.message;
    }
  }

  $effect(() => {
    if (opStatus === 'failed') busy = false;
  });

  onDestroy(() => { stopPolling(); stopRenderPolling(); });
</script>

<div class="mx-auto flex min-h-full w-full max-w-3xl flex-col px-6 py-10">
  {#if busy}
    <div class="mx-auto w-full max-w-xl">
      <GenerationProgress status={opStatus} {stages} error={opError} onopen={() => goto('/scenes')} />
    </div>
  {:else}
    <div class="mb-8">
      <div class="mb-3 flex size-10 items-center justify-center rounded-xl bg-primary/10 text-primary">
        <Clapperboard class="size-5" />
      </div>
      <h1 class="text-2xl font-semibold tracking-tight">Create a video</h1>
      <p class="mt-2 max-w-xl text-muted-foreground">
        Describe the story. VideoFlow builds scenes, dialogue, visuals, and render jobs. Provider calls may incur charges.
      </p>
    </div>

    <form class="space-y-5" onsubmit={createVideo}>
      <div class="rounded-xl border border-border bg-card p-5 shadow-sm">
        <label class="mb-2 block text-sm font-medium" for="idea">What video do you want to make?</label>
        <textarea
          id="idea"
          bind:value={idea}
          required
          placeholder="A warm 2D story about two siblings learning why families celebrate the Mid-Autumn Festival…"
          class="min-h-40 w-full resize-y rounded-lg border border-input bg-background px-3 py-2.5 text-sm outline-none focus:ring-2 focus:ring-ring"
        ></textarea>
      </div>

      <div class="grid gap-3 sm:grid-cols-2">
        <label class="grid gap-1.5 text-sm">
          <span class="font-medium">Visual style</span>
          {#if preflight?.has_project_style}
            <span class="rounded-lg border border-input bg-muted px-3 py-2">{preflight.effective_style} · project style</span>
          {:else}
            <select bind:value={style} class="rounded-lg border border-input bg-background px-3 py-2 text-sm">
              <option value="2d-picture-book">2D picture book</option>
              <option value="cinematic">Cinematic</option>
            </select>
          {/if}
        </label>
        <label class="grid gap-1.5 text-sm">
          <span class="font-medium">Format</span>
          <select bind:value={aspectRatio} class="rounded-lg border border-input bg-background px-3 py-2 text-sm">
            <option value="9:16">Vertical · 9:16</option>
            <option value="16:9">Landscape · 16:9</option>
            <option value="1:1">Square · 1:1</option>
          </select>
        </label>
        <label class="grid gap-1.5 text-sm">
          <span class="font-medium">Language</span>
          <select bind:value={language} class="rounded-lg border border-input bg-background px-3 py-2 text-sm">
            <option>English</option>
            <option>Chinese</option>
            <option>Malay</option>
          </select>
        </label>
        <div class="grid gap-1.5 text-sm">
          <span class="font-medium">Dialogue</span>
          <span class="text-muted-foreground">Conversational dialogue is applied to generated scenes.</span>
        </div>
      </div>

      <div class="rounded-lg border border-border bg-card p-4 text-sm">
        <h2 class="font-medium">Before you create</h2>
        <p class="mt-2 text-muted-foreground">
          Request brief: {language} dialogue, {aspectRatio} format, {preflight?.effective_style ?? style} visual style.
          {#if instruction.trim()} Direction: {instruction.trim()}{:else} No extra direction added.{/if}
        </p>
        {#if preflightError}
          <p class="mt-2 text-destructive">Could not check provider setup: {preflightError}</p>
        {:else if !preflight}
          <p class="mt-2 text-muted-foreground">Checking configured models and supported video settings…</p>
        {:else}
          <p class="mt-2">Effective project style: <strong>{preflight.effective_style}</strong></p>
          <p class="mt-1 text-muted-foreground">This request plans a story, scenes, shots, dialogue, storyboard images, and video render jobs. Image provider: {preflight.routes.image.provider} (storyboards). Character and prop images use AtlasCloud. Video: {preflight.routes.video.provider} / {preflight.routes.video.model || 'no model selected'} (up to {preflight.routes.video.max_duration}s, {preflight.routes.video.max_reference_images} image references).</p>
          {#each preflight.warnings ?? [] as warning}
            <p class="mt-2 text-amber-700 dark:text-amber-300">Unverified route: {warning.reason}</p>
          {/each}
          {#if preflight.missing.length}
            <ul class="mt-2 list-disc space-y-1 pl-5 text-destructive">
              {#each preflight.missing as item}
                <li>{item.reason} <a class="underline" href={item.setting}>Open settings</a></li>
              {/each}
            </ul>
          {:else}
            <p class="mt-2 text-emerald-700 dark:text-emerald-300">Configured routes and selected format are ready. This check does not contact providers.</p>
          {/if}
        {/if}
      </div>

      <details class="rounded-lg border border-border px-4 py-3 text-sm">
        <summary class="cursor-pointer font-medium">More options</summary>
        <div class="mt-3 grid gap-3 sm:grid-cols-2">
          <label class="grid gap-1.5">
            <span class="text-muted-foreground">Target duration in seconds</span>
            <input type="number" min="3" max="300" bind:value={duration} placeholder="Automatic" class="rounded-lg border border-input bg-background px-3 py-2" />
          </label>
          <label class="grid gap-1.5 sm:col-span-2">
            <span class="text-muted-foreground">Direction for the AI</span>
            <input bind:value={instruction} placeholder="Warm, clear dialogue with short lines…" class="rounded-lg border border-input bg-background px-3 py-2" />
          </label>
        </div>
      </details>

      {#if opError}
        <p class="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{opError}</p>
      {/if}

      {#if lastResult && opStatus !== 'running'}
        <div class="rounded-lg border border-border p-4 text-sm">
          <p class="font-medium">{opStatus === 'failed' ? 'Existing work is preserved.' : opStatus === 'completed' ? 'Video complete.' : 'Render jobs submitted.'}</p>
          <p class="mt-1 text-muted-foreground">Open existing scenes to inspect completed work. Creating again starts a new pipeline and may repeat paid stages.</p>
          <div class="mt-3 flex flex-wrap gap-2">
            <Button type="button" variant="secondary" onclick={() => goto('/scenes')}>Open existing scenes</Button>
            <Button type="button" variant="outline" onclick={() => goto('/render')}>Open render jobs</Button>
            {#if opStatus === 'failed'}
              <Button type="button" variant="outline" onclick={() => { opId = ''; opError = ''; opStatus = ''; lastResult = null; }}>Start a new generation</Button>
            {/if}
          </div>
        </div>
      {/if}

      <Button type="submit" size="lg" class="w-full sm:w-auto" disabled={!idea.trim() || !preflight || preflight.missing.length > 0 || !!preflightError}>
        <Sparkles class="mr-2 size-4" />Create video
      </Button>
    </form>
  {/if}
</div>
