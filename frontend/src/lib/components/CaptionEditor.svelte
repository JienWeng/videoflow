<script lang="ts">
  /**
   * Caption editor: review every subtitle line (text + timing), fix mistakes
   * and re-burn — without re-running whisper.
   *
   * The preview plays the RAW video (captions are burned into a copy) with a
   * styled overlay showing the CURRENT segment's text driven by `timeupdate`,
   * which gives WYSIWYG-ish feedback without re-burning.
   */
  import { onMount } from 'svelte';
  import { get, mediaUrl } from '$lib/api';
  import { runBackgroundOp } from '$lib/ops';
  import { Button } from '$lib/components/ui/button';
  import { Input } from '$lib/components/ui/input';
  import { toast } from 'svelte-sonner';
  import { Play, Plus, RotateCcw, Trash2 } from '@lucide/svelte';

  type Segment = { start: number; end: number; text: string };

  let {
    outputId,
    videoPath,
    onsaved
  }: { outputId: string; videoPath: string | null | undefined; onsaved?: () => void } = $props();

  let segments = $state<Segment[]>([]);
  let style = $state('');
  let styles = $state<string[]>([]);
  let available = $state(false);
  let loading = $state(true);
  let saving = $state(false);
  let loadError = $state('');

  let videoEl: HTMLVideoElement | undefined = $state();
  let currentTime = $state(0);

  const videoSrc = $derived(mediaUrl(videoPath));
  const activeIndex = $derived(
    segments.findIndex((s) => currentTime >= s.start && currentTime < s.end)
  );
  const activeText = $derived(activeIndex >= 0 ? segments[activeIndex].text : '');

  async function load() {
    loading = true;
    loadError = '';
    try {
      const r = await get(`/outputs/${outputId}/captions`);
      available = !!r.available;
      segments = (r.segments ?? []).map((s: Segment) => ({ ...s }));
      style = r.style ?? '';
    } catch (err: any) {
      loadError = err.message;
    } finally {
      loading = false;
    }
  }

  onMount(() => {
    void load();
    get('/caption-config')
      .then((cfg: any) => {
        styles = cfg.styles ?? [];
        if (!style) style = cfg.default_style || styles[0] || '';
      })
      .catch(() => {});
  });

  function playFrom(seg: Segment) {
    if (!videoEl) return;
    videoEl.currentTime = seg.start;
    void videoEl.play();
  }

  function addLine() {
    const t = Math.round((videoEl?.currentTime ?? 0) * 10) / 10;
    segments = [...segments, { start: t, end: t + 2, text: '' }];
  }

  function removeLine(i: number) {
    segments = segments.filter((_, idx) => idx !== i);
  }

  async function save() {
    saving = true;
    try {
      await runBackgroundOp(
        `/outputs/${outputId}/captions`,
        {
          // Number() guards against number-input values arriving as strings.
          segments: segments.map((s) => ({
            start: Number(s.start),
            end: Number(s.end),
            text: s.text
          })),
          style: style || null
        },
        {
          method: 'PUT',
          label: 'Re-burning captions',
          onDone: () => {
            saving = false;
            void load();
            onsaved?.();
          },
          onFail: () => (saving = false)
        }
      );
    } catch (err: any) {
      saving = false;
      toast.error(err.message);
    }
  }

  const hasText = $derived(segments.some((s) => s.text.trim()));
</script>

<div class="flex flex-col gap-3">
  {#if loading}
    <p class="text-sm text-muted-foreground">Loading captions…</p>
  {:else if loadError}
    <p class="text-sm text-destructive">{loadError}</p>
  {:else if !available && segments.length === 0 && !videoSrc}
    <p class="text-sm text-muted-foreground">No video file available.</p>
  {:else}
    {#if videoSrc}
      <div class="relative">
        <!-- svelte-ignore a11y_media_has_caption -->
        <video
          bind:this={videoEl}
          controls
          src={videoSrc}
          class="w-full rounded-md border border-border"
          ontimeupdate={() => (currentTime = videoEl?.currentTime ?? 0)}
        ></video>
        {#if activeText}
          <div
            class="pointer-events-none absolute inset-x-3 bottom-12 text-center text-base font-bold text-white"
            style="text-shadow: 0 0 4px #000, 0 0 8px #000;"
          >
            {activeText}
          </div>
        {/if}
      </div>
    {/if}

    {#if !available && segments.length === 0}
      <p class="text-xs text-muted-foreground">
        Not captioned yet — add lines manually or run auto-captions first.
      </p>
    {/if}

    <div class="flex max-h-72 flex-col gap-1.5 overflow-y-auto pr-1">
      {#each segments as seg, i (i)}
        <div
          class="flex items-center gap-1.5 rounded-md border px-1.5 py-1 {i === activeIndex
            ? 'border-primary bg-primary/10'
            : 'border-border'}"
        >
          <span class="w-5 shrink-0 text-right text-xs text-muted-foreground">{i + 1}</span>
          <Input
            type="number"
            step={0.1}
            min={0}
            bind:value={seg.start}
            class="h-7 w-[4.5rem] px-1.5 text-xs"
            aria-label="Start (s)"
          />
          <Input
            type="number"
            step={0.1}
            min={0}
            bind:value={seg.end}
            class="h-7 w-[4.5rem] px-1.5 text-xs"
            aria-label="End (s)"
          />
          <Input bind:value={seg.text} class="h-7 flex-1 px-2 text-xs" aria-label="Caption text" />
          <Button
            variant="ghost"
            size="icon"
            class="size-7 shrink-0"
            title="Play from here"
            onclick={() => playFrom(seg)}
          >
            <Play class="size-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            class="size-7 shrink-0 text-destructive"
            title="Delete line"
            onclick={() => removeLine(i)}
          >
            <Trash2 class="size-3.5" />
          </Button>
        </div>
      {/each}
    </div>

    <div class="flex flex-wrap items-center gap-2">
      <Button variant="outline" size="sm" onclick={addLine}>
        <Plus class="size-3.5 mr-1" />Add line
      </Button>
      <div class="grow"></div>
      {#if styles.length}
        <select
          bind:value={style}
          class="rounded border border-input bg-background px-1.5 py-1 text-xs"
          aria-label="Caption style"
        >
          {#each styles as st (st)}<option value={st}>{st}</option>{/each}
        </select>
      {/if}
      <Button variant="outline" size="sm" disabled={saving} onclick={() => void load()}>
        <RotateCcw class="size-3.5 mr-1" />Revert
      </Button>
      <Button size="sm" disabled={saving || !hasText} onclick={save}>
        {saving ? 'Re-burning…' : 'Save & re-burn'}
      </Button>
    </div>
  {/if}
</div>
