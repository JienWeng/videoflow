<script lang="ts">
  import { onDestroy } from 'svelte';
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
  let poller: ReturnType<typeof setInterval> | null = null;

  function stopPolling() {
    if (poller) clearInterval(poller);
    poller = null;
  }

  async function checkOperation() {
    if (!opId) return;
    try {
      const op = await get(`/ops/${opId}`);
      opStatus = op.status;
      stages = op.result_json?.stages ?? stages;
      if (op.status === 'succeeded') {
        stopPolling();
        await goto('/render');
      } else if (op.status === 'failed') {
        stopPolling();
        opError = op.error || 'The generation failed.';
      }
    } catch (e: any) {
      opError = e.message;
    }
  }

  async function createVideo(e: SubmitEvent) {
    e.preventDefault();
    if (!idea.trim() || busy) return;
    busy = true;
    opError = '';
    stages = [];
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

  onDestroy(stopPolling);
</script>

<div class="mx-auto flex min-h-full w-full max-w-3xl flex-col px-6 py-10">
  {#if busy}
    <div class="mx-auto w-full max-w-xl">
      <GenerationProgress status={opStatus} {stages} error={opError} />
    </div>
  {:else}
    <div class="mb-8">
      <div class="mb-3 flex size-10 items-center justify-center rounded-xl bg-primary/10 text-primary">
        <Clapperboard class="size-5" />
      </div>
      <h1 class="text-2xl font-semibold tracking-tight">Create a video</h1>
      <p class="mt-2 max-w-xl text-muted-foreground">
        Describe the story. VideoFlow will build the scenes, dialogue, visuals, and render for you.
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
          <select bind:value={style} class="rounded-lg border border-input bg-background px-3 py-2 text-sm">
            <option value="2d-picture-book">2D picture book</option>
            <option value="cinematic">Cinematic</option>
          </select>
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
        <label class="grid gap-1.5 text-sm">
          <span class="font-medium">Dialogue</span>
          <select bind:value={conversationMode} class="rounded-lg border border-input bg-background px-3 py-2 text-sm">
            <option value="dialogue">Conversational</option>
            <option value="narration">Narrated</option>
            <option value="off">Keep original style</option>
          </select>
        </label>
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

      <Button type="submit" size="lg" class="w-full sm:w-auto" disabled={!idea.trim()}>
        <Sparkles class="mr-2 size-4" />Create video
      </Button>
    </form>
  {/if}
</div>
