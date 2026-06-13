<script lang="ts">
  /**
   * Contextual right panel: caption form / shot form / output summary,
   * driven by the timeline selection.
   */
  import { patch, post } from '$lib/api';
  import { runBackgroundOp } from '$lib/ops';
  import { Button } from '$lib/components/ui/button';
  import { Input } from '$lib/components/ui/input';
  import { Label } from '$lib/components/ui/label';
  import { Textarea } from '$lib/components/ui/textarea';
  import { Separator } from '$lib/components/ui/separator';
  import { toast } from 'svelte-sonner';
  import { ArrowUpToLine, RefreshCw, ShieldCheck, Trash2 } from '@lucide/svelte';
  import type { EditorOutput, SceneRef, Segment, Selection, Shot } from './types';

  let {
    selection,
    segments,
    shots,
    output,
    scene,
    style = $bindable(),
    styles,
    focusSignal = 0,
    ondirty,
    ondeletecaption,
    onmergeprev,
    onretried,
    onqarun
  }: {
    selection: Selection;
    segments: Segment[];
    shots: Shot[];
    output: EditorOutput;
    scene: SceneRef;
    style?: string;
    styles: string[];
    focusSignal?: number;
    ondirty: () => void;
    ondeletecaption: (i: number) => void;
    onmergeprev: (i: number) => void;
    onretried: () => void;
    /** Called after a quality check completes so the parent can reload the score. */
    onqarun?: () => void;
  } = $props();

  // QA state, derived from the output (no qa_status on EditorOutput yet -> infer).
  const scored = $derived(output.score != null);

  const seg = $derived(selection?.kind === 'caption' ? segments[selection.index] : null);
  const shot = $derived(selection?.kind === 'shot' ? shots[selection.index] : null);

  // --- Caption text focus (timeline double-click) ---
  let textEl: HTMLTextAreaElement | null = $state(null);
  $effect(() => {
    if (focusSignal > 0 && textEl) {
      textEl.focus();
      textEl.select();
    }
  });

  function setTime(field: 'start' | 'end', raw: string) {
    if (!seg) return;
    const v = Number(raw);
    if (!Number.isFinite(v)) return;
    seg[field] = Math.max(0, v);
    ondirty();
  }

  // --- Shot form: local copy, re-seeded when the selected shot changes ---
  let shotForm = $state({ prompt: '', camera: '', movement: '' });
  let savingShot = $state(false);
  $effect(() => {
    shotForm = {
      prompt: shot?.prompt ?? '',
      camera: shot?.camera ?? '',
      movement: shot?.movement ?? ''
    };
  });

  async function saveShot() {
    if (!shot?.shot_id) return;
    savingShot = true;
    try {
      await patch(`/shots/${shot.shot_id}`, {
        prompt: shotForm.prompt,
        camera: shotForm.camera,
        movement: shotForm.movement
      });
      // Reflect locally so re-selecting shows the saved values.
      shot.prompt = shotForm.prompt;
      shot.camera = shotForm.camera;
      shot.movement = shotForm.movement;
      toast.success('Shot saved');
    } catch (err: any) {
      toast.error(err.message);
    } finally {
      savingShot = false;
    }
  }

  // --- Output summary actions ---
  let retrying = $state(false);
  async function fixAndRerender() {
    retrying = true;
    try {
      const res = await post(`/outputs/${output.id}/retry`);
      toast.success(`Corrective re-render started — job ${res.job_id}`);
      onretried();
    } catch (err: any) {
      toast.error(err.message);
    } finally {
      retrying = false;
    }
  }

  let qaRunning = $state(false);
  async function runQualityCheck() {
    qaRunning = true;
    try {
      await runBackgroundOp(`/outputs/${output.id}/run-qa`, undefined, {
        label: 'Quality check',
        onDone: () => {
          qaRunning = false;
          onqarun?.();
        },
        onFail: () => (qaRunning = false)
      });
    } catch (err: any) {
      qaRunning = false;
      toast.error(err.message);
    }
  }
</script>

<div class="flex h-full flex-col gap-4 overflow-y-auto p-4">
  {#if seg && selection}
    <div>
      <h3 class="text-sm font-semibold">Caption</h3>
      <p class="text-xs text-muted-foreground">Line {selection.index + 1} of {segments.length}</p>
    </div>
    <div class="grid gap-1.5">
      <Label for="insp-text">Text</Label>
      <Textarea
        id="insp-text"
        rows={3}
        bind:ref={textEl}
        value={seg.text}
        oninput={(e) => {
          seg.text = (e.currentTarget as HTMLTextAreaElement).value;
          ondirty();
        }}
      />
    </div>
    <div class="grid grid-cols-2 gap-3">
      <div class="grid gap-1.5">
        <Label for="insp-start">Start (s)</Label>
        <Input
          id="insp-start"
          type="number"
          step={0.1}
          min={0}
          value={Number(seg.start)}
          oninput={(e) => setTime('start', (e.currentTarget as HTMLInputElement).value)}
        />
      </div>
      <div class="grid gap-1.5">
        <Label for="insp-end">End (s)</Label>
        <Input
          id="insp-end"
          type="number"
          step={0.1}
          min={0}
          value={Number(seg.end)}
          oninput={(e) => setTime('end', (e.currentTarget as HTMLInputElement).value)}
        />
      </div>
    </div>
    {#if styles.length}
      <div class="grid gap-1.5">
        <Label for="insp-style">Style (all captions)</Label>
        <select
          id="insp-style"
          class="rounded-md border border-input bg-background px-2 py-1.5 text-sm"
          value={style ?? ''}
          onchange={(e) => {
            style = (e.currentTarget as HTMLSelectElement).value;
            ondirty();
          }}
        >
          {#each styles as st (st)}<option value={st}>{st}</option>{/each}
        </select>
      </div>
    {/if}
    <Separator />
    {#if selection.index > 0}
      <Button
        variant="outline"
        size="sm"
        title="Fold this caption into the previous one (joins text, extends its end)"
        onclick={() => selection && onmergeprev(selection.index)}
      >
        <ArrowUpToLine class="mr-1 size-3.5" />Merge into previous
      </Button>
    {/if}
    <Button
      variant="destructive"
      size="sm"
      onclick={() => selection && ondeletecaption(selection.index)}
    >
      <Trash2 class="mr-1 size-3.5" />Delete caption
    </Button>
  {:else if shot}
    <div>
      <h3 class="text-sm font-semibold">Shot #{shot.index}</h3>
      <p class="text-xs text-muted-foreground">
        {shot.start.toFixed(1)}–{shot.end.toFixed(1)}s · {shot.duration}s
      </p>
    </div>
    {#if shot.shot_id}
      <div class="grid gap-1.5">
        <Label for="insp-prompt">Prompt</Label>
        <Textarea id="insp-prompt" rows={6} bind:value={shotForm.prompt} />
      </div>
      <div class="grid gap-1.5">
        <Label for="insp-camera">Camera</Label>
        <Input id="insp-camera" bind:value={shotForm.camera} />
      </div>
      <div class="grid gap-1.5">
        <Label for="insp-movement">Movement</Label>
        <Input id="insp-movement" bind:value={shotForm.movement} />
      </div>
      <Button size="sm" disabled={savingShot} onclick={saveShot}>
        {savingShot ? 'Saving…' : 'Save shot'}
      </Button>
      <p class="text-xs text-muted-foreground">
        Shot edits apply to the NEXT render — this video keeps its baked-in timing.
      </p>
    {:else}
      <div class="grid gap-1.5">
        <Label>Prompt (from render spec)</Label>
        <p class="whitespace-pre-wrap rounded-md border border-border bg-muted/40 p-2 text-xs">
          {shot.prompt || '(empty)'}
        </p>
      </div>
      <p class="text-xs text-muted-foreground">
        Read-only: this block comes from the stored render spec and has no live shot row.
      </p>
    {/if}
  {:else}
    <div>
      <h3 class="text-sm font-semibold">Output</h3>
      <p class="break-all font-mono text-xs text-muted-foreground">{output.id}</p>
    </div>
    <div class="grid gap-1.5">
      <Label>QA score</Label>
      <p class="text-sm">{scored ? `${output.score}/10` : 'not scored'}</p>
    </div>
    {#if !scored}
      <Button
        variant="outline"
        size="sm"
        title="Score this take against the scene requirements — unlocks Fix & re-render"
        disabled={qaRunning}
        onclick={runQualityCheck}
      >
        <ShieldCheck class="mr-1 size-3.5" />
        {qaRunning ? 'Checking…' : 'Run quality check'}
      </Button>
    {/if}
    {#if output.qa_issues.length}
      <div class="grid gap-1.5">
        <Label>Issues</Label>
        <ul class="space-y-1 text-xs text-muted-foreground">
          {#each output.qa_issues as issue (issue)}
            <li title={issue}>- {issue}</li>
          {/each}
        </ul>
      </div>
      <Button variant="secondary" size="sm" disabled={retrying} onclick={fixAndRerender}>
        <RefreshCw class="mr-1 size-3.5 {retrying ? 'animate-spin' : ''}" />
        {retrying ? 'Submitting…' : 'Fix & re-render'}
      </Button>
    {/if}
    <Separator />
    {#if scene}
      <div class="grid gap-1.5">
        <Label>Scene</Label>
        <a href="/scenes" class="text-sm text-primary hover:underline">{scene.title}</a>
      </div>
    {/if}
    <p class="text-xs text-muted-foreground">
      Select a caption or shot block on the timeline to edit it here.
    </p>
  {/if}
</div>
