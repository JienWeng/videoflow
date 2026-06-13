<script lang="ts">
  import { Handle, Position, type NodeProps } from '@xyflow/svelte';
  import { Users, Image, Clapperboard, ListVideo, Film } from '@lucide/svelte';
  import { Badge } from '$lib/components/ui/badge';
  import { mediaUrl, isImage } from '$lib/api';
  import { kindColor } from './transform';

  let { data }: NodeProps = $props();

  const icons: Record<string, typeof Users> = {
    character: Users,
    asset: Image,
    scene: Clapperboard,
    shot: ListVideo,
    render_job: Film,
    output: Film
  };

  const kind = $derived(String(data.kind ?? ''));
  const Icon = $derived(icons[kind] ?? Film);
  const preview = $derived(
    kind === 'asset' && isImage(data.file_path as string)
      ? mediaUrl(data.file_path as string)
      : kind === 'output' && data.thumbnail_path
        ? mediaUrl(data.thumbnail_path as string)
        : null
  );
  const status = $derived(kind === 'render_job' ? String(data.status ?? '') : null);
  const badgeVariant = $derived(
    status === 'succeeded' ? 'default' : status === 'failed' ? 'destructive' : 'secondary'
  );
</script>

<!-- Kind-tinted left border: at far zoom levels labels vanish, but the accent
  colors keep the graph readable as structure-by-color (matches the minimap). -->
<div
  class="w-[180px] rounded-md border border-l-2 bg-card px-2 py-1.5 text-xs shadow-sm
    {kind === 'scene' ? 'border-primary/60' : 'border-border'}"
  style="border-left-color: {kindColor(kind)}"
>
  <!-- A large, grabbable handle on EACH side. The default xyflow handles are
    ~2-3px wide — effectively un-grabbable once the user zooms to a workable
    level (the reported "can't drag asset→shot" bug). With connectionMode="loose"
    (set on SvelteFlow) every handle acts as both source and target, so a drag
    can begin/end on either side regardless of cluster layout direction.
    handleConnect normalizes by kind, so orientation doesn't matter. -->
  <Handle id="l" type="source" position={Position.Left} class="entity-handle" />
  <div class="flex items-center gap-1.5">
    <Icon class="size-3.5 shrink-0 text-muted-foreground" />
    <span class="truncate font-medium" title={String(data.label ?? '')}>{data.label}</span>
  </div>
  {#if preview}
    <img src={preview} alt={String(data.label ?? '')} class="mt-1 h-16 w-full rounded object-cover" />
  {/if}
  {#if status}
    <div class="mt-1">
      <Badge variant={badgeVariant}>{status}</Badge>
    </div>
  {/if}
  <Handle id="r" type="source" position={Position.Right} class="entity-handle" />
</div>

<style>
  /* Big, reliably grabbable hit area above the node content/image. The visible
     dot stays modest, but the pointer target is generous so a hand-aimed drag
     actually starts/ends on the handle. */
  :global(.svelte-flow__handle.entity-handle) {
    width: 14px;
    height: 14px;
    border-radius: 9999px;
    background: hsl(0 0% 60%);
    border: 2px solid hsl(0 0% 18%);
    z-index: 20;
    pointer-events: all;
  }
  /* Overlapping source+target on the same side: keep both fully clickable by
     letting the topmost win the visual but both share the same center. */
  :global(.svelte-flow__handle.entity-handle:hover) {
    background: hsl(150 60% 50%);
  }
</style>
