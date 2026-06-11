<script lang="ts">
  import type { Node } from '@xyflow/svelte';
  import * as Sheet from '$lib/components/ui/sheet';
  import { Button } from '$lib/components/ui/button';
  import { Input } from '$lib/components/ui/input';
  import { Label } from '$lib/components/ui/label';
  import { Textarea } from '$lib/components/ui/textarea';
  import { Badge } from '$lib/components/ui/badge';
  import { toast } from 'svelte-sonner';
  import { History, Sparkles, Trash2 } from '@lucide/svelte';
  import { get, patch, post, del, mediaUrl, isImage } from '$lib/api';

  let {
    node,
    onclose,
    onsaved
  }: { node: Node | null; onclose: () => void; onsaved: () => void } = $props();

  const kind = $derived(String(node?.data?.kind ?? ''));
  const data = $derived((node?.data ?? {}) as Record<string, any>);

  // Editable form state, re-seeded whenever the selected node changes.
  let form = $state<Record<string, any>>({});
  let saving = $state(false);
  let refineInstruction = $state('');
  let refining = $state(false);
  let confirmingDelete = $state(false);
  let deleting = $state(false);
  let confirmTimer: ReturnType<typeof setTimeout> | undefined;
  let showHistory = $state(false);
  let revisions = $state<any[]>([]);
  let reverting = $state('');

  $effect(() => {
    const d = (node?.data ?? {}) as Record<string, any>;
    refineInstruction = '';
    confirmingDelete = false;
    showHistory = false;
    revisions = [];
    if (node && String(d.kind) === 'scene') {
      form = {
        title: d.label ?? '',
        summary: d.summary ?? '',
        duration: d.duration ?? 0,
        aspect_ratio: d.aspect_ratio ?? ''
      };
    } else if (node && String(d.kind) === 'shot') {
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
  });

  async function save() {
    if (!node) return;
    saving = true;
    try {
      if (kind === 'scene') {
        await patch(`/scenes/${node.id}`, {
          title: form.title,
          summary: form.summary,
          duration: Number(form.duration),
          aspect_ratio: form.aspect_ratio
        });
      } else if (kind === 'shot') {
        await patch(`/shots/${node.id}`, {
          prompt: form.prompt,
          duration: Number(form.duration),
          camera: form.camera,
          movement: form.movement,
          shot_order: Number(form.shot_order)
        });
      }
      toast.success('Saved');
      onsaved();
    } catch (err: any) {
      toast.error(err.message);
    } finally {
      saving = false;
    }
  }

  async function refine() {
    if (!node || !refineInstruction.trim()) return;
    refining = true;
    try {
      if (kind === 'scene') {
        const r = await post(`/scenes/${node.id}/refine`, { instruction: refineInstruction.trim() });
        form = {
          title: r.scene.title ?? '',
          summary: r.scene.summary ?? '',
          duration: r.scene.duration ?? 0,
          aspect_ratio: r.scene.aspect_ratio ?? ''
        };
        toast.success(r.note || 'Refined');
      } else if (kind === 'shot') {
        const r = await post(`/shots/${node.id}/refine`, { instruction: refineInstruction.trim() });
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
      onsaved();
    } catch (err: any) {
      toast.error(err.message);
    } finally {
      refining = false;
    }
  }

  function seedForm(e: Record<string, any>) {
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
    if (!node) return;
    showHistory = !showHistory;
    if (!showHistory) return;
    try {
      revisions = await get(`/${kind}s/${node.id}/revisions`);
    } catch (err: any) {
      toast.error(err.message);
    }
  }

  async function revert(revisionId: string) {
    if (!node) return;
    reverting = revisionId;
    try {
      const entity = await post(`/revisions/${revisionId}/revert`);
      seedForm(entity);
      revisions = await get(`/${kind}s/${node.id}/revisions`);
      toast.success('Reverted');
      onsaved();
    } catch (err: any) {
      toast.error(err.message);
    } finally {
      reverting = '';
    }
  }

  async function deleteAsset() {
    if (!node) return;
    if (!confirmingDelete) {
      confirmingDelete = true;
      clearTimeout(confirmTimer);
      confirmTimer = setTimeout(() => (confirmingDelete = false), 3000);
      return;
    }
    clearTimeout(confirmTimer);
    deleting = true;
    try {
      const r = await del(`/assets/${node.id}`);
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

<Sheet.Root open={node !== null} onOpenChange={(open) => !open && onclose()}>
  <Sheet.Content side="right" class="w-[380px] sm:max-w-[380px]">
    <Sheet.Header>
      <Sheet.Title class="capitalize">{kind.replace('_', ' ')}</Sheet.Title>
      <Sheet.Description class="truncate">{data.label}</Sheet.Description>
    </Sheet.Header>

    <div class="flex flex-col gap-4 overflow-y-auto px-4 pb-4">
      {#if kind === 'scene'}
        <div class="grid gap-1.5">
          <Label for="np-title">Title</Label>
          <Input id="np-title" bind:value={form.title} />
        </div>
        <div class="grid gap-1.5">
          <Label for="np-summary">Summary</Label>
          <Textarea id="np-summary" rows={4} bind:value={form.summary} />
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div class="grid gap-1.5">
            <Label for="np-duration">Duration (s)</Label>
            <Input id="np-duration" type="number" bind:value={form.duration} />
          </div>
          <div class="grid gap-1.5">
            <Label for="np-aspect">Aspect ratio</Label>
            <Input id="np-aspect" bind:value={form.aspect_ratio} />
          </div>
        </div>
        <div class="flex gap-2">
          <Input placeholder="Tell AI what to change…" bind:value={refineInstruction} />
          <Button variant="outline" onclick={refine} disabled={refining || !refineInstruction.trim()}>
            <Sparkles class="size-4 mr-1" />{refining ? 'Refining…' : 'AI refine'}
          </Button>
        </div>
        <Button onclick={save} disabled={saving}>{saving ? 'Saving…' : 'Save'}</Button>
      {:else if kind === 'shot'}
        <div class="grid gap-1.5">
          <Label for="np-prompt">Prompt</Label>
          <Textarea id="np-prompt" rows={5} bind:value={form.prompt} />
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div class="grid gap-1.5">
            <Label for="np-shot-duration">Duration (s)</Label>
            <Input id="np-shot-duration" type="number" bind:value={form.duration} />
          </div>
          <div class="grid gap-1.5">
            <Label for="np-order">Order</Label>
            <Input id="np-order" type="number" bind:value={form.shot_order} />
          </div>
        </div>
        <div class="grid gap-1.5">
          <Label for="np-camera">Camera</Label>
          <Input id="np-camera" bind:value={form.camera} />
        </div>
        <div class="grid gap-1.5">
          <Label for="np-movement">Movement</Label>
          <Input id="np-movement" bind:value={form.movement} />
        </div>
        <div class="flex gap-2">
          <Input placeholder="Tell AI what to change…" bind:value={refineInstruction} />
          <Button variant="outline" onclick={refine} disabled={refining || !refineInstruction.trim()}>
            <Sparkles class="size-4 mr-1" />{refining ? 'Refining…' : 'AI refine'}
          </Button>
        </div>
        <Button onclick={save} disabled={saving}>{saving ? 'Saving…' : 'Save'}</Button>
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
