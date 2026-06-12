<script lang="ts" module>
  // Caption config is project-wide — fetch once per app session, lazily on
  // the first output-node selection, and share across panel instances.
  type CaptionConfig = {
    styles: string[];
    models: string[];
    default_model: string;
    default_language: string;
    default_style: string;
  };
  let captionConfigPromise: Promise<CaptionConfig> | null = null;
</script>

<script lang="ts">
  import { untrack } from 'svelte';
  import type { Node } from '@xyflow/svelte';
  import * as Sheet from '$lib/components/ui/sheet';
  import { Button } from '$lib/components/ui/button';
  import { Input } from '$lib/components/ui/input';
  import { Label } from '$lib/components/ui/label';
  import { Textarea } from '$lib/components/ui/textarea';
  import { Badge } from '$lib/components/ui/badge';
  import { Separator } from '$lib/components/ui/separator';
  import { toast } from 'svelte-sonner';
  import { Captions, Clapperboard, History, Pencil, RefreshCw, Sparkles, Trash2 } from '@lucide/svelte';
  import { get, patch, post, del, mediaUrl, isImage } from '$lib/api';
  import { runBackgroundOp } from '$lib/ops';
  import CaptionEditor from '$lib/components/CaptionEditor.svelte';

  let {
    node,
    onclose,
    onsaved
  }: { node: Node | null; onclose: () => void; onsaved: () => void } = $props();

  // The panel's own source of truth for which node it shows. It tracks the
  // `node` prop, EXCEPT when the form is dirty and the user cancels the
  // discard confirm — then the new selection is ignored and the panel keeps
  // the node being edited (we can't revert the parent's selection from here).
  let shown = $state<Node | null>(null);
  // Sheet open state is locally bound so a refused close can be re-opened —
  // bits-ui flips its (unbound) open prop internally, so merely "not closing"
  // in onOpenChange is not enough to keep the sheet visible.
  let sheetOpen = $state(false);

  const kind = $derived(String(shown?.data?.kind ?? ''));
  const data = $derived((shown?.data ?? {}) as Record<string, any>);

  // Editable form state, re-seeded whenever the selected node changes.
  let form = $state<Record<string, any>>({});
  // True once any form field was touched; reset on seed/save/refine/revert.
  let formDirty = $state(false);
  const markFormDirty = () => (formDirty = true);
  let saving = $state(false);
  let refineInstruction = $state('');
  let refining = $state(false);
  let confirmingDelete = $state(false);
  let deleting = $state(false);
  let confirmTimer: ReturnType<typeof setTimeout> | undefined;
  let showHistory = $state(false);
  let revisions = $state<any[]>([]);
  let reverting = $state('');

  // Output node actions (QA retry + captions)
  let retrying = $state(false);
  let captioning = $state(false);
  let captionStyles = $state<string[]>([]);
  let captionModels = $state<string[]>([]);
  let captionStyle = $state('');
  let captionModel = $state('');
  let captionLanguage = $state('zh');
  // Caption editor is lazy: only mounted (and its captions fetched) when opened.
  let editingCaptions = $state(false);

  // Sync the `node` prop into `shown`, guarding unsaved edits on node-switch.
  // Design note: reverting the parent's selection on cancel is impractical
  // (selection lives in +page.svelte and there is no "reselect" callback), so
  // we accept confirm-then-discard semantics: proceed only on OK; on cancel
  // the incoming selection is simply ignored and the panel keeps `shown`.
  $effect(() => {
    const next = node;
    untrack(() => {
      if ((next?.id ?? null) === (shown?.id ?? null)) return;
      if (formDirty && shown && !confirm('Discard unsaved changes?')) return;
      shown = next;
      sheetOpen = next !== null;
    });
  });

  // Re-seed the form whenever the shown node changes.
  $effect(() => {
    const d = (shown?.data ?? {}) as Record<string, any>;
    refineInstruction = '';
    confirmingDelete = false;
    showHistory = false;
    revisions = [];
    editingCaptions = false;
    formDirty = false;
    if (shown && String(d.kind) === 'scene') {
      form = {
        title: d.label ?? '',
        summary: d.summary ?? '',
        duration: d.duration ?? 0,
        aspect_ratio: d.aspect_ratio ?? ''
      };
    } else if (shown && String(d.kind) === 'shot') {
      form = {
        prompt: d.prompt ?? '',
        duration: d.duration ?? 0,
        camera: d.camera ?? '',
        movement: d.movement ?? '',
        shot_order: d.shot_order ?? 0
      };
    } else {
      form = {};
    }
    if (shown && String(d.kind) === 'output') void loadCaptionConfig();
  });

  // Close requested via Escape / overlay / X. bits-ui has already flipped
  // sheetOpen to false by the time onOpenChange fires, so refusing the close
  // means flipping it back (the confirm dialog blocks, so no visible flicker).
  function requestClose() {
    if (formDirty && !confirm('Discard unsaved changes?')) {
      sheetOpen = true;
      return;
    }
    formDirty = false;
    onclose();
  }

  async function loadCaptionConfig() {
    captionConfigPromise ??= get('/caption-config');
    try {
      const cfg = await captionConfigPromise;
      captionStyles = cfg.styles ?? [];
      captionModels = cfg.models ?? [];
      captionStyle = cfg.default_style || captionStyles[0] || 'kids';
      captionModel = cfg.default_model || captionModels[0] || '';
      captionLanguage = cfg.default_language || 'zh';
    } catch {
      captionConfigPromise = null; // allow retry on next selection
    }
  }

  async function fixAndRerender() {
    if (!shown) return;
    retrying = true;
    try {
      const res = await post(`/outputs/${shown.id}/retry`);
      toast.success(`Corrective re-render started — job ${res.job_id}`);
      onsaved();
    } catch (err: any) {
      toast.error(err.message);
    } finally {
      retrying = false;
    }
  }

  async function addCaptions() {
    if (!shown) return;
    captioning = true;
    try {
      await runBackgroundOp(
        `/outputs/${shown.id}/caption`,
        {
          style: captionStyle || undefined,
          model: captionModel || undefined,
          language: captionLanguage === 'auto' ? null : captionLanguage
        },
        {
          label: 'Captioning',
          onDone: () => {
            captioning = false;
            onsaved();
          },
          onFail: () => (captioning = false)
        }
      );
    } catch (err: any) {
      captioning = false;
      toast.error(err.message);
    }
  }

  async function save() {
    if (!shown) return;
    saving = true;
    try {
      if (kind === 'scene') {
        await patch(`/scenes/${shown.id}`, {
          title: form.title,
          summary: form.summary,
          duration: Number(form.duration),
          aspect_ratio: form.aspect_ratio
        });
      } else if (kind === 'shot') {
        await patch(`/shots/${shown.id}`, {
          prompt: form.prompt,
          duration: Number(form.duration),
          camera: form.camera,
          movement: form.movement,
          shot_order: Number(form.shot_order)
        });
      }
      formDirty = false;
      toast.success('Saved');
      onsaved();
    } catch (err: any) {
      toast.error(err.message);
    } finally {
      saving = false;
    }
  }

  async function refine() {
    if (!shown || !refineInstruction.trim()) return;
    refining = true;
    try {
      if (kind === 'scene') {
        const r = await post(`/scenes/${shown.id}/refine`, { instruction: refineInstruction.trim() });
        form = {
          title: r.scene.title ?? '',
          summary: r.scene.summary ?? '',
          duration: r.scene.duration ?? 0,
          aspect_ratio: r.scene.aspect_ratio ?? ''
        };
        toast.success(r.note || 'Refined');
      } else if (kind === 'shot') {
        const r = await post(`/shots/${shown.id}/refine`, { instruction: refineInstruction.trim() });
        form = {
          prompt: r.shot.prompt ?? '',
          duration: r.shot.duration ?? 0,
          camera: r.shot.camera ?? '',
          movement: r.shot.movement ?? '',
          shot_order: r.shot.shot_order ?? 0
        };
        toast.success(r.note || 'Refined');
      }
      refineInstruction = '';
      formDirty = false; // form now mirrors the server-side refined entity
      onsaved();
    } catch (err: any) {
      toast.error(err.message);
    } finally {
      refining = false;
    }
  }

  function seedForm(e: Record<string, any>) {
    formDirty = false;
    if (kind === 'scene') {
      form = {
        title: e.title ?? '',
        summary: e.summary ?? '',
        duration: e.duration ?? 0,
        aspect_ratio: e.aspect_ratio ?? ''
      };
    } else if (kind === 'shot') {
      form = {
        prompt: e.prompt ?? '',
        duration: e.duration ?? 0,
        camera: e.camera ?? '',
        movement: e.movement ?? '',
        shot_order: e.shot_order ?? 0
      };
    }
  }

  async function toggleHistory() {
    if (!shown) return;
    showHistory = !showHistory;
    if (!showHistory) return;
    try {
      revisions = await get(`/${kind}s/${shown.id}/revisions`);
    } catch (err: any) {
      toast.error(err.message);
    }
  }

  async function revert(revisionId: string) {
    if (!shown) return;
    reverting = revisionId;
    try {
      const entity = await post(`/revisions/${revisionId}/revert`);
      seedForm(entity);
      revisions = await get(`/${kind}s/${shown.id}/revisions`);
      toast.success('Reverted');
      onsaved();
    } catch (err: any) {
      toast.error(err.message);
    } finally {
      reverting = '';
    }
  }

  async function deleteAsset() {
    if (!shown) return;
    if (!confirmingDelete) {
      confirmingDelete = true;
      clearTimeout(confirmTimer);
      confirmTimer = setTimeout(() => (confirmingDelete = false), 3000);
      return;
    }
    clearTimeout(confirmTimer);
    deleting = true;
    try {
      const r = await del(`/assets/${shown.id}`);
      toast.success(`Asset deleted (detached from ${r.detached_from} place${r.detached_from === 1 ? '' : 's'}).`);
      onsaved();
      onclose();
    } catch (err: any) {
      toast.error(err.message);
    } finally {
      deleting = false;
      confirmingDelete = false;
    }
  }

  const videoSrc = $derived(
    kind === 'output' ? mediaUrl(data.captioned_path || data.video_path) : null
  );
  const imageSrc = $derived(
    kind === 'asset' && isImage(data.file_path) ? mediaUrl(data.file_path) : null
  );
</script>

<Sheet.Root bind:open={sheetOpen} onOpenChange={(open) => !open && requestClose()}>
  <Sheet.Content side="right" class="w-[380px] sm:max-w-[380px]">
    <Sheet.Header>
      <Sheet.Title class="capitalize">{kind.replace('_', ' ')}</Sheet.Title>
      <Sheet.Description class="truncate">{data.label}</Sheet.Description>
    </Sheet.Header>

    <div class="flex flex-col gap-4 overflow-y-auto px-4 pb-4">
      {#if kind === 'scene'}
        <div class="grid gap-1.5">
          <Label for="np-title">Title</Label>
          <Input id="np-title" bind:value={form.title} oninput={markFormDirty} />
        </div>
        <div class="grid gap-1.5">
          <Label for="np-summary">Summary</Label>
          <Textarea id="np-summary" rows={4} bind:value={form.summary} oninput={markFormDirty} />
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div class="grid gap-1.5">
            <Label for="np-duration">Duration (s)</Label>
            <Input id="np-duration" type="number" bind:value={form.duration} oninput={markFormDirty} />
          </div>
          <div class="grid gap-1.5">
            <Label for="np-aspect">Aspect ratio</Label>
            <Input id="np-aspect" bind:value={form.aspect_ratio} oninput={markFormDirty} />
          </div>
        </div>
        <div class="flex gap-2">
          <Input placeholder="Tell AI what to change…" bind:value={refineInstruction} />
          <Button variant="outline" onclick={refine} disabled={refining || !refineInstruction.trim()}>
            <Sparkles class="size-4 mr-1" />{refining ? 'Refining…' : 'AI refine'}
          </Button>
        </div>
        <div class="flex items-center gap-2">
          <Button class="flex-1" onclick={save} disabled={saving}>{saving ? 'Saving…' : 'Save'}</Button>
          {#if formDirty}
            <Badge variant="outline" class="text-muted-foreground">unsaved</Badge>
          {/if}
        </div>
      {:else if kind === 'shot'}
        <div class="grid gap-1.5">
          <Label for="np-prompt">Prompt</Label>
          <Textarea id="np-prompt" rows={5} bind:value={form.prompt} oninput={markFormDirty} />
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div class="grid gap-1.5">
            <Label for="np-shot-duration">Duration (s)</Label>
            <Input id="np-shot-duration" type="number" bind:value={form.duration} oninput={markFormDirty} />
          </div>
          <div class="grid gap-1.5">
            <Label for="np-order">Order</Label>
            <Input id="np-order" type="number" bind:value={form.shot_order} oninput={markFormDirty} />
          </div>
        </div>
        <div class="grid gap-1.5">
          <Label for="np-camera">Camera</Label>
          <Input id="np-camera" bind:value={form.camera} oninput={markFormDirty} />
        </div>
        <div class="grid gap-1.5">
          <Label for="np-movement">Movement</Label>
          <Input id="np-movement" bind:value={form.movement} oninput={markFormDirty} />
        </div>
        <div class="flex gap-2">
          <Input placeholder="Tell AI what to change…" bind:value={refineInstruction} />
          <Button variant="outline" onclick={refine} disabled={refining || !refineInstruction.trim()}>
            <Sparkles class="size-4 mr-1" />{refining ? 'Refining…' : 'AI refine'}
          </Button>
        </div>
        <div class="flex items-center gap-2">
          <Button class="flex-1" onclick={save} disabled={saving}>{saving ? 'Saving…' : 'Save'}</Button>
          {#if formDirty}
            <Badge variant="outline" class="text-muted-foreground">unsaved</Badge>
          {/if}
        </div>
      {:else if kind === 'output'}
        {#if videoSrc}
          <!-- svelte-ignore a11y_media_has_caption -->
          <video controls src={videoSrc} class="w-full rounded-md border border-border"></video>
        {:else}
          <p class="text-sm text-muted-foreground">No video file available.</p>
        {/if}
        <div class="text-xs text-muted-foreground">
          {#if data.captioned_path}<p class="truncate">Captioned: {data.captioned_path}</p>{/if}
          {#if data.video_path}<p class="truncate">Video: {data.video_path}</p>{/if}
        </div>

        <Separator />

        <div class="grid gap-1.5">
          <Label>Quality check</Label>
          <p class="text-sm">QA: {data.score ?? '—'}{data.score != null ? '/10' : ''}</p>
          {#if data.qa_issues?.length}
            <ul class="text-xs text-muted-foreground space-y-0.5">
              {#each data.qa_issues.slice(0, 3) as issue (issue)}
                <li class="truncate" title={issue}>- {issue}</li>
              {/each}
            </ul>
            <Button variant="secondary" size="sm" disabled={retrying} onclick={fixAndRerender}>
              <RefreshCw class="size-4 mr-1 {retrying ? 'animate-spin' : ''}" />
              {retrying ? 'Submitting…' : 'Fix & re-render'}
            </Button>
          {/if}
        </div>

        <Separator />

        <div class="grid gap-1.5">
          <Label>Captions</Label>
          <div class="flex flex-wrap items-center gap-1">
            {#if captionStyles.length}
              <select
                bind:value={captionStyle}
                class="rounded border border-input bg-background px-1.5 py-1 text-xs"
              >
                {#each captionStyles as st (st)}<option value={st}>{st}</option>{/each}
              </select>
            {/if}
            {#if captionModels.length}
              <select
                bind:value={captionModel}
                class="rounded border border-input bg-background px-1.5 py-1 text-xs"
              >
                {#each captionModels as m (m)}<option value={m}>{m}</option>{/each}
              </select>
            {/if}
            <select
              bind:value={captionLanguage}
              class="rounded border border-input bg-background px-1.5 py-1 text-xs w-16"
            >
              <option value="zh">zh</option>
              <option value="en">en</option>
              <option value="auto">auto</option>
            </select>
          </div>
          <Button variant="outline" size="sm" disabled={captioning} onclick={addCaptions}>
            <Captions class="size-4 mr-1" />
            {captioning ? 'Transcribing…' : data.captioned_path ? 'Re-caption' : 'Auto captions'}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            class="justify-start"
            onclick={() => (editingCaptions = !editingCaptions)}
          >
            <Pencil class="size-4 mr-1" />
            {editingCaptions ? 'Hide caption editor' : 'Edit captions'}
          </Button>
          {#if editingCaptions && shown}
            <CaptionEditor outputId={shown.id} videoPath={data.video_path} onsaved={onsaved} />
          {/if}
        </div>

        <Separator />

        <Button variant="outline" size="sm" href={`/editor/${shown?.id}`}>
          <Clapperboard class="size-4 mr-1" />Open in editor
        </Button>
      {:else if kind === 'asset'}
        {#if imageSrc}
          <img src={imageSrc} alt={String(data.label ?? '')} class="w-full rounded-md border border-border object-cover" />
        {/if}
        <div class="grid gap-2 text-sm">
          <div class="flex justify-between gap-2">
            <span class="text-muted-foreground">Type</span>
            <span>{data.asset_type}</span>
          </div>
          <div class="flex justify-between gap-2">
            <span class="text-muted-foreground">File</span>
            <span class="truncate">{data.file_path}</span>
          </div>
        </div>
        <Button variant="destructive" onclick={deleteAsset} disabled={deleting}>
          <Trash2 class="size-4 mr-1" />
          {deleting ? 'Deleting…' : confirmingDelete ? 'Confirm delete' : 'Delete asset'}
        </Button>
      {:else if kind === 'render_job'}
        <div class="flex items-center gap-2 text-sm">
          <span class="text-muted-foreground">Status</span>
          <Badge
            variant={data.status === 'succeeded'
              ? 'default'
              : data.status === 'failed'
                ? 'destructive'
                : 'secondary'}>{data.status}</Badge
          >
        </div>
      {:else if kind === 'character'}
        <p class="text-sm">{data.label}</p>
      {/if}

      {#if kind === 'scene' || kind === 'shot'}
        <div class="grid gap-2 border-t border-border pt-3">
          <Button variant="ghost" size="sm" class="justify-start" onclick={toggleHistory}>
            <History class="size-4 mr-1" />
            {showHistory ? 'Hide history' : 'History'}
          </Button>
          {#if showHistory}
            {#if revisions.length === 0}
              <p class="px-2 text-xs text-muted-foreground">No edits recorded yet.</p>
            {:else}
              {#each revisions as rev (rev.id)}
                <div class="flex items-center justify-between gap-2 rounded-md border border-border px-2 py-1.5">
                  <div class="min-w-0 text-xs">
                    <p class="truncate font-medium">{Object.keys(rev.fields_json).join(', ')}</p>
                    <p class="text-muted-foreground">
                      {new Date(rev.created_at).toLocaleString()} · {rev.source}
                    </p>
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    onclick={() => revert(rev.id)}
                    disabled={reverting !== ''}
                  >
                    {reverting === rev.id ? 'Reverting…' : 'Revert'}
                  </Button>
                </div>
              {/each}
            {/if}
          {/if}
        </div>
      {/if}
    </div>
  </Sheet.Content>
</Sheet.Root>
