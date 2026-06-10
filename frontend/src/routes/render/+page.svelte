<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { get, post } from '$lib/api';
  import VideoPreview from '$lib/components/VideoPreview.svelte';
  import { Button } from '$lib/components/ui/button';
  import { Badge } from '$lib/components/ui/badge';
  import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '$lib/components/ui/table';
  import { toast } from 'svelte-sonner';
  import { Play, Captions } from '@lucide/svelte';

  let jobs: any[] = $state([]);
  let scenes: any[] = $state([]);
  let shots: any[] = $state([]);
  let outputs: Record<string, any[]> = $state({});
  let error = $state('');
  let busy = $state(false);

  let sceneId = $state('');
  let shotId = $state('');

  // Caption config
  let captionStyles: string[] = $state([]);
  let captionModels: string[] = $state([]);
  let captionDefaultModel = $state('');
  let captionDefaultLanguage = $state('zh');
  let captionStyle: Record<string, string> = $state({});
  let captionModel: Record<string, string> = $state({});
  let captionLanguage: Record<string, string> = $state({});
  let captioning = $state('');

  let timer: ReturnType<typeof setInterval>;

  async function refresh() {
    [jobs, scenes] = await Promise.all([get('/render-jobs'), get('/scenes')]);
    const done = jobs.filter((j) => j.status === 'succeeded');
    for (const j of done) {
      if (!outputs[j.id]) {
        const detail = await get(`/render-jobs/${j.id}`);
        outputs[j.id] = detail.outputs;
      }
    }
    outputs = outputs;
  }

  onMount(() => {
    refresh().catch((e) => (error = e.message));
    get('/caption-config')
      .then((cfg: any) => {
        captionStyles = cfg.styles ?? [];
        captionModels = cfg.models ?? [];
        captionDefaultModel = cfg.default_model ?? '';
        captionDefaultLanguage = cfg.default_language ?? 'zh';
      })
      .catch(() => {
        // Fallback to legacy endpoint
        get('/caption-styles').then((s) => (captionStyles = s)).catch(() => {});
      });
    timer = setInterval(() => refresh().catch(() => {}), 5000);
  });
  onDestroy(() => clearInterval(timer));

  async function addCaptions(jobId: string, out: any) {
    captioning = out.id;
    error = '';
    try {
      const lang = captionLanguage[out.id] ?? captionDefaultLanguage ?? 'zh';
      const updated = await post(`/outputs/${out.id}/caption`, {
        style: captionStyle[out.id] ?? captionStyles[0] ?? 'kids',
        model: captionModel[out.id] ?? (captionDefaultModel || undefined),
        language: lang === 'auto' ? null : lang
      });
      outputs[jobId] = outputs[jobId].map((o) => (o.id === out.id ? updated : o));
      outputs = outputs;
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      captioning = '';
    }
  }

  async function loadShots() {
    shots = sceneId ? await get(`/scenes/${sceneId}/shots`) : [];
    shotId = '';
  }

  async function renderFromShot(e: Event) {
    e.preventDefault();
    busy = true;
    error = '';
    try {
      await post('/render/from-shot', { scene_id: sceneId, shot_id: shotId });
      await refresh();
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      busy = false;
    }
  }

  function statusVariant(status: string): 'default' | 'destructive' | 'secondary' | 'outline' {
    if (status === 'succeeded') return 'default';
    if (status === 'failed') return 'destructive';
    return 'secondary';
  }
</script>

<div class="p-6">
  <h1 class="text-lg font-semibold mb-4">Render</h1>

  <form class="mb-4 rounded-lg border border-border bg-card p-4" onsubmit={renderFromShot}>
    <div class="flex flex-wrap gap-4 items-end">
      <div class="flex-1 min-w-[160px]">
        <label class="block text-xs text-muted-foreground mb-1" for="scene">Scene</label>
        <select id="scene" bind:value={sceneId} onchange={loadShots}
          class="w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm">
          <option value="">choose…</option>
          {#each scenes as s}<option value={s.id}>{s.title}</option>{/each}
        </select>
      </div>
      <div class="flex-1 min-w-[160px]">
        <label class="block text-xs text-muted-foreground mb-1" for="shot">Shot (prompt-agent render)</label>
        <select id="shot" bind:value={shotId} disabled={!shots.length}
          class="w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm">
          <option value="">choose…</option>
          {#each shots as sh}<option value={sh.id}>#{sh.shot_order + 1} {sh.prompt.slice(0, 50)}</option>{/each}
        </select>
      </div>
      <div>
        <Button type="submit" disabled={busy || !shotId} size="sm">
          <Play class="size-4 mr-1" />Render shot
        </Button>
      </div>
    </div>
    <div class="text-xs text-muted-foreground mt-2">Whole-scene multi-shot renders live on the Scenes page (step 4).</div>
  </form>

  <Table>
    <TableHeader>
      <TableRow>
        <TableHead>job</TableHead>
        <TableHead>scene / shot</TableHead>
        <TableHead>model</TableHead>
        <TableHead>status</TableHead>
        <TableHead>error</TableHead>
      </TableRow>
    </TableHeader>
    <TableBody>
      {#each jobs.slice().reverse() as j (j.id)}
        <TableRow>
          <TableCell class="text-xs font-mono">{j.id}</TableCell>
          <TableCell class="text-xs">{j.scene_id}{j.shot_id ? ` / ${j.shot_id}` : ''}</TableCell>
          <TableCell class="text-xs">{j.model?.split('/').slice(-2).join('/')}</TableCell>
          <TableCell>
            <Badge variant={statusVariant(j.status)}>{j.status}</Badge>
          </TableCell>
          <TableCell class="text-xs text-muted-foreground">{j.error ?? ''}</TableCell>
        </TableRow>
        {#if outputs[j.id]?.length}
          <TableRow>
            <TableCell colspan={5}>
              <div class="flex flex-wrap gap-4 py-1">
                {#each outputs[j.id] as out (out.id)}
                  <div class="flex-none">
                    <VideoPreview path={out.captioned_path || out.video_path} />
                    <div class="text-xs text-muted-foreground mt-1 flex items-center gap-1">
                      QA: {out.score ?? '—'} {out.qa_json?.recommendation ?? ''}
                      {#if out.captioned_path}<Badge class="ml-1">captioned</Badge>{/if}
                    </div>
                    <div class="flex flex-wrap items-center gap-1 mt-1">
                      {#if captionStyles.length}
                        <select
                          bind:value={captionStyle[out.id]}
                          class="rounded border border-input bg-background px-1.5 py-1 text-xs"
                        >
                          {#each captionStyles as st}<option value={st}>{st}</option>{/each}
                        </select>
                      {/if}
                      {#if captionModels.length}
                        <select
                          bind:value={captionModel[out.id]}
                          class="rounded border border-input bg-background px-1.5 py-1 text-xs"
                        >
                          {#each captionModels as m}<option value={m}>{m}</option>{/each}
                        </select>
                      {/if}
                      <select
                        bind:value={captionLanguage[out.id]}
                        class="rounded border border-input bg-background px-1.5 py-1 text-xs w-16"
                      >
                        <option value="zh">zh</option>
                        <option value="en">en</option>
                        <option value="auto">auto</option>
                      </select>
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={!!captioning}
                        onclick={() => addCaptions(j.id, out)}
                      >
                        <Captions class="size-3 mr-1" />
                        {captioning === out.id ? 'transcribing…' : out.captioned_path ? 'Re-caption' : 'Auto captions'}
                      </Button>
                    </div>
                  </div>
                {/each}
              </div>
            </TableCell>
          </TableRow>
        {/if}
      {/each}
    </TableBody>
  </Table>
</div>
