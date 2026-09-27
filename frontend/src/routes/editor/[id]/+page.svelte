<script lang="ts">
  /**
   * Video editor: preview player + zoomable multi-track timeline + inspector.
   *
   * Plays the RAW video with a live caption overlay (WYSIWYG); saving re-burns the subtitles into the captioned copy via
   * the background-op flow. Shot edits PATCH the live shot rows and only
   * affect the NEXT render.
   */
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import { beforeNavigate } from '$app/navigation';
  import { get, mediaUrl, API_BASE } from '$lib/api';
  import { runBackgroundOp } from '$lib/ops';
  import { Button } from '$lib/components/ui/button';
  import { Badge } from '$lib/components/ui/badge';
  import { Skeleton } from '$lib/components/ui/skeleton';
  import { toast } from 'svelte-sonner';
  import {
    ArrowLeft,
    Download,
    Pause,
    Play,
    Save,
    Sparkles,
    ZoomIn,
    ZoomOut
  } from '@lucide/svelte';
  import Timeline from '$lib/editor/Timeline.svelte';
  import Inspector from '$lib/editor/Inspector.svelte';
  import type { EditorOutput, SceneRef, Segment, Selection, Shot } from '$lib/editor/types';

  const outputId = $derived(page.params.id ?? '');

  // --- Data ---
  let loading = $state(true);
  let loadError = $state('');
  let output = $state<EditorOutput | null>(null);
  let segments = $state<Segment[]>([]);
  let style = $state('');
  let styles = $state<string[]>([]);
  let shots = $state<Shot[]>([]);
  let scene = $state<SceneRef>(null);
  let specDuration = $state(0);

  // --- Transcription (auto-captions, whisper) ---
  let models = $state<string[]>([]);
  let model = $state('');
  let languages = $state<{ value: string; label: string }[]>([
    { value: 'auto', label: 'Auto-detect' },
    { value: 'zh', label: 'Chinese' },
    { value: 'en', label: 'English' }
  ]);
  let language = $state('auto');
  let transcribing = $state(false);
  const hasCaptions = $derived(segments.length > 0);

  // --- Player ---
  let videoEl: HTMLVideoElement | undefined = $state();
  let currentTime = $state(0);
  let playing = $state(false);
  let videoDuration = $state(0);
  let raf = 0;

  // --- Timeline view ---
  let viewWidth = $state(0); // scroller width, bound from Timeline
  let zoom = $state(1); // 1 = fit-to-width; pps clamps to [fit, 200]
  const MAX_PPS = 200;

  // --- Editing ---
  let selection = $state<Selection>(null);
  let dirty = $state(false);
  let saving = $state(false);
  let focusSignal = $state(0);

  const totalDuration = $derived(
    Math.max(
      specDuration,
      videoDuration,
      ...segments.map((s) => Number(s.end) || 0),
      1
    )
  );
  const fitPps = $derived(
    viewWidth > 0 ? Math.min(viewWidth / totalDuration, MAX_PPS) : 40
  );
  const pps = $derived(Math.min(Math.max(fitPps * zoom, fitPps), MAX_PPS));

  const videoSrc = $derived(mediaUrl(output?.video_path));
  const activeText = $derived(
    segments.find((s) => currentTime >= Number(s.start) && currentTime < Number(s.end))?.text ?? ''
  );

  async function load() {
    loading = true;
    loadError = '';
    try {
      const r = await get(`/outputs/${outputId}/editor`);
      output = r.output;
      segments = (r.captions?.segments ?? []).map((s: Segment) => ({
        start: Number(s.start),
        end: Number(s.end),
        text: s.text ?? ''
      }));
      style = r.captions?.style ?? '';
      shots = r.shots ?? [];
      scene = r.scene ?? null;
      specDuration = Number(r.total_duration) || 0;
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
        models = cfg.models ?? [];
        model = cfg.default_model || models[0] || '';
        // Make sure the resolved default language is selectable.
        const defLang = cfg.default_language || 'auto';
        if (!languages.some((l) => l.value === defLang)) {
          languages = [...languages, { value: defLang, label: defLang }];
        }
        language = defLang;
      })
      .catch(() => {});
    return () => cancelAnimationFrame(raf);
  });

  beforeNavigate((nav) => {
    if (dirty && !confirm('You have unsaved caption changes. Leave anyway?')) nav.cancel();
  });

  // --- Transport ---
  function tick() {
    if (videoEl && !videoEl.paused && !videoEl.ended) {
      currentTime = videoEl.currentTime;
      raf = requestAnimationFrame(tick);
    }
  }

  function togglePlay() {
    if (!videoEl) return;
    if (videoEl.paused) void videoEl.play();
    else videoEl.pause();
  }

  function seek(t: number) {
    currentTime = t;
    if (videoEl) videoEl.currentTime = t;
  }

  function fmt(t: number): string {
    const m = Math.floor(t / 60);
    const s = t - m * 60;
    return `${m}:${s.toFixed(1).padStart(4, '0')}`;
  }

  function zoomBy(factor: number) {
    const maxZoom = fitPps > 0 ? MAX_PPS / fitPps : 1;
    zoom = Math.min(Math.max(zoom * factor, 1), Math.max(maxZoom, 1));
  }

  // --- Caption editing ---
  function markDirty() {
    dirty = true;
  }

  const r3 = (n: number) => Math.round(n * 1000) / 1000;

  function addCaption() {
    const start = r3(Math.min(currentTime, Math.max(0, totalDuration - 0.3)));
    const end = r3(Math.min(start + 2, totalDuration));
    segments = [...segments, { start, end: r3(Math.max(end, start + 0.3)), text: '' }];
    selection = { kind: 'caption', index: segments.length - 1 };
    focusSignal += 1;
    dirty = true;
  }

  function deleteCaption(i: number) {
    segments = segments.filter((_, idx) => idx !== i);
    selection = null;
    dirty = true;
  }

  /** Fold caption i into i-1: join the texts (space, unless identical),
   * extend the previous segment's end to cover this one, drop this one. */
  function mergePrevCaption(i: number) {
    const prev = segments[i - 1];
    const cur = segments[i];
    if (!prev || !cur) return;
    const a = (prev.text ?? '').trim();
    const b = (cur.text ?? '').trim();
    prev.text = a === b ? a : [a, b].filter(Boolean).join(' ');
    prev.end = r3(Math.max(Number(prev.end), Number(cur.end)));
    segments = segments.filter((_, idx) => idx !== i);
    selection = { kind: 'caption', index: i - 1 };
    dirty = true;
  }

  async function save() {
    if (!output) return;
    saving = true;
    try {
      await runBackgroundOp(
        `/outputs/${output.id}/captions`,
        {
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
            // Only a successful burn makes the page clean — clearing dirty on
            // mere acceptance would let a failed re-burn masquerade as saved
            // (and disarm the beforeNavigate guard).
            saving = false;
            dirty = false;
            void load();
          },
          onFail: () => {
            // ops.ts already toasts the failure; keep the page dirty so the
            // unsaved-changes indicator and nav guard stay armed.
            saving = false;
            dirty = true;
          }
        }
      );
    } catch (err: any) {
      saving = false;
      toast.error(err.message);
    }
  }

  // --- Auto-transcribe (whisper -> editable segments, NO burn) ---
  async function transcribe() {
    if (!output || transcribing) return;
    // Replacing existing captions is destructive — confirm first.
    if (hasCaptions && !confirm('Re-transcribe will replace the current captions. Continue?')) {
      return;
    }
    transcribing = true;
    try {
      await runBackgroundOp(
        `/outputs/${output.id}/captions/transcribe`,
        { model: model || null, language: language || null },
        {
          label: hasCaptions ? 'Re-transcribing' : 'Transcribing',
          onDone: () => {
            transcribing = false;
            // Re-fetch so the freshly transcribed segments appear on the
            // timeline, ready to edit. Transcription is a fresh, on-disk
            // source of truth -> clear the dirty flag.
            dirty = false;
            selection = null;
            void load();
          },
          onFail: () => {
            transcribing = false;
          }
        }
      );
    } catch (err: any) {
      transcribing = false;
      toast.error(err.message);
    }
  }

  function downloadUrl(variant: 'raw' | 'captioned'): string {
    return `${API_BASE}/outputs/${outputId}/download?variant=${variant}`;
  }

  // --- Keyboard shortcuts (guarded against typing in inputs) ---
  function isTyping(t: EventTarget | null): boolean {
    const el = t as HTMLElement | null;
    if (!el) return false;
    const tag = el.tagName;
    return (
      tag === 'INPUT' ||
      tag === 'TEXTAREA' ||
      tag === 'SELECT' ||
      el.isContentEditable === true
    );
  }

  function onKeydown(e: KeyboardEvent) {
    // Cmd/Ctrl+S works even from inputs (a deliberate save), everything else is
    // suppressed while typing so it doesn't hijack normal text entry.
    const save_combo = (e.metaKey || e.ctrlKey) && (e.key === 's' || e.key === 'S');
    if (save_combo) {
      e.preventDefault();
      if (dirty && !saving) void save();
      return;
    }
    if (isTyping(e.target) || e.metaKey || e.ctrlKey || e.altKey) return;

    switch (e.key) {
      case ' ':
        e.preventDefault();
        togglePlay();
        break;
      case 'ArrowLeft':
        e.preventDefault();
        seek(Math.max(0, currentTime - (e.shiftKey ? 5 : 1)));
        break;
      case 'ArrowRight':
        e.preventDefault();
        seek(Math.min(totalDuration, currentTime + (e.shiftKey ? 5 : 1)));
        break;
      case 'Delete':
        if (selection?.kind === 'caption') {
          e.preventDefault();
          deleteCaption(selection.index);
        }
        break;
    }
  }
</script>

<svelte:window onkeydown={onKeydown} />

<svelte:head>
  <title>Editor — {scene?.title ?? outputId}</title>
</svelte:head>

<div class="flex h-screen flex-col">
  {#if loading}
    <div class="p-6 space-y-4">
      <Skeleton class="h-8 w-72" />
      <Skeleton class="mx-auto aspect-video w-full max-w-3xl rounded-lg" />
      <Skeleton class="h-24 w-full rounded-lg" />
    </div>
  {:else if loadError || !output}
    <div class="p-6">
      <p class="text-sm text-destructive">{loadError || 'Output not found.'}</p>
      <Button variant="outline" size="sm" href="/render" class="mt-3">
        <ArrowLeft class="mr-1 size-3.5" />Back to renders
      </Button>
    </div>
  {:else}
    <!-- Header -->
    <header class="flex items-center gap-3 border-b border-border px-4 py-2">
      <Button variant="ghost" size="icon-sm" href="/render" title="Back to renders">
        <ArrowLeft />
      </Button>
      <div class="min-w-0">
        <h1 class="truncate text-sm font-semibold">{scene?.title ?? 'Video editor'}</h1>
        <p class="truncate font-mono text-[11px] text-muted-foreground">{output.id}</p>
      </div>
      {#if output.score != null}
        <Badge variant={output.score >= 7 ? 'default' : 'destructive'}>QA {output.score}/10</Badge>
      {/if}
      {#if output.qa_issues.length}
        <Badge variant="outline">{output.qa_issues.length} issue{output.qa_issues.length === 1 ? '' : 's'}</Badge>
      {/if}
      <div class="grow"></div>
      {#if dirty}
        <span class="text-xs text-muted-foreground">unsaved changes</span>
      {/if}
      <!-- Auto-transcribe: whisper -> editable caption segments (no burn).
           The editor is the single place to transcribe -> edit -> re-burn. -->
      <div class="flex items-center gap-1.5">
        {#if models.length}
          <select
            class="h-8 rounded-md border border-input bg-background px-2 text-xs"
            bind:value={model}
            disabled={transcribing}
            title="Whisper model (larger = more accurate, slower)"
          >
            {#each models as m (m)}<option value={m}>{m}</option>{/each}
          </select>
        {/if}
        <select
          class="h-8 rounded-md border border-input bg-background px-2 text-xs"
          bind:value={language}
          disabled={transcribing}
          title="Spoken language for transcription"
        >
          {#each languages as l (l.value)}<option value={l.value}>{l.label}</option>{/each}
        </select>
        <Button
          variant="secondary"
          size="sm"
          disabled={transcribing}
          onclick={transcribe}
          title={hasCaptions
            ? 'Re-run transcription and replace the current captions'
            : 'Transcribe the video into editable caption segments'}
        >
          <Sparkles class="mr-1 size-3.5 {transcribing ? 'animate-pulse' : ''}" />
          {transcribing
            ? 'Transcribing…'
            : hasCaptions
              ? 'Re-transcribe'
              : 'Auto-transcribe'}
        </Button>
      </div>
      <!-- Download: captioned copy when it exists, plus the raw original. -->
      {#if output.captioned_path}
        <Button
          variant="secondary"
          size="sm"
          href={downloadUrl('captioned')}
          download
          title="Download the captioned video"
        >
          <Download class="mr-1 size-3.5" />Captioned
        </Button>
      {/if}
      <Button
        variant={output.captioned_path ? 'ghost' : 'secondary'}
        size="sm"
        href={downloadUrl('raw')}
        download
        title="Download the original (uncaptioned) video"
      >
        <Download class="mr-1 size-3.5" />Raw
      </Button>
      <Button size="sm" disabled={!dirty || saving} onclick={save}>
        <Save class="mr-1 size-3.5" />
        {saving ? 'Re-burning…' : 'Save'}
      </Button>
    </header>

    <!-- Main -->
    <div class="flex min-h-0 min-w-0 flex-1 flex-col md:flex-row">
      <!-- Left: player + transport + timeline -->
      <div class="flex min-w-0 flex-1 flex-col gap-3 p-4">
        <div class="relative mx-auto min-h-0 w-full max-w-3xl flex-1">
          {#if videoSrc}
            <!-- svelte-ignore a11y_media_has_caption -->
            <video
              bind:this={videoEl}
              src={videoSrc}
              poster={mediaUrl(output?.thumbnail_path) ?? undefined}
              class="h-full w-full rounded-lg border border-border bg-black object-contain"
              onclick={togglePlay}
              onplay={() => {
                playing = true;
                raf = requestAnimationFrame(tick);
              }}
              onpause={() => {
                playing = false;
                currentTime = videoEl?.currentTime ?? currentTime;
              }}
              onended={() => (playing = false)}
              ontimeupdate={() => {
                if (!playing) currentTime = videoEl?.currentTime ?? currentTime;
              }}
              onloadedmetadata={() => (videoDuration = videoEl?.duration ?? 0)}
            ></video>
            {#if activeText}
              <div
                class="pointer-events-none absolute inset-x-4 bottom-8 text-center text-lg font-bold text-white"
                style="text-shadow: 0 0 4px #000, 0 0 8px #000;"
              >
                {activeText}
              </div>
            {/if}
          {:else}
            <div
              class="flex h-full items-center justify-center rounded-lg border border-border text-sm text-muted-foreground"
            >
              No video file available.
            </div>
          {/if}
        </div>

        <!-- Transport bar -->
        <div class="flex items-center gap-3">
          <Button variant="outline" size="icon-sm" onclick={togglePlay} title={playing ? 'Pause' : 'Play'}>
            {#if playing}<Pause />{:else}<Play />{/if}
          </Button>
          <span class="font-mono text-xs tabular-nums text-muted-foreground">
            {fmt(currentTime)} / {fmt(totalDuration)}
          </span>
          <div class="grow"></div>
          <Button variant="ghost" size="icon-sm" title="Zoom out" disabled={zoom <= 1} onclick={() => zoomBy(1 / 1.5)}>
            <ZoomOut />
          </Button>
          <span class="w-14 text-center text-xs tabular-nums text-muted-foreground">
            {pps.toFixed(0)} px/s
          </span>
          <Button
            variant="ghost"
            size="icon-sm"
            title="Zoom in"
            disabled={pps >= MAX_PPS}
            onclick={() => zoomBy(1.5)}
          >
            <ZoomIn />
          </Button>
          <Button variant="ghost" size="sm" disabled={zoom <= 1} onclick={() => (zoom = 1)}>Fit</Button>
        </div>

        <!-- Empty captions: prompt the user to auto-transcribe right here. -->
        {#if !hasCaptions}
          <div
            class="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-dashed border-border bg-muted/30 px-4 py-3"
          >
            <p class="text-xs text-muted-foreground">
              Auto-transcribe the voice track to add editable captions.
            </p>
            <Button variant="secondary" size="sm" disabled={transcribing} onclick={transcribe}>
              <Sparkles class="mr-1 size-3.5 {transcribing ? 'animate-pulse' : ''}" />
              {transcribing ? 'Transcribing…' : 'Auto-transcribe'}
            </Button>
          </div>
        {/if}

        <!-- Timeline -->
        <Timeline
          {shots}
          {segments}
          {totalDuration}
          {pps}
          {currentTime}
          {selection}
          bind:viewWidth
          onseek={seek}
          onselect={(sel) => (selection = sel)}
          ondirty={markDirty}
          onaddcaption={addCaption}
          oncaptiondblclick={(i) => {
            selection = { kind: 'caption', index: i };
            focusSignal += 1;
          }}
        />
      </div>

      <!-- Right: inspector -->
      <aside class="w-full shrink-0 border-t border-border md:w-80 md:border-l md:border-t-0">
        <Inspector
          {selection}
          {segments}
          {shots}
          {output}
          {scene}
          bind:style
          {styles}
          {focusSignal}
          {transcribing}
          ondirty={markDirty}
          ondeletecaption={deleteCaption}
          onmergeprev={mergePrevCaption}
          onretried={() => {}}
          onqarun={() => void load()}
          ontranscribe={transcribe}
        />
      </aside>
    </div>
  {/if}
</div>
