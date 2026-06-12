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
  <Handle type="target" position={Position.Left} />
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
  <Handle type="source" position={Position.Right} />
</div>
