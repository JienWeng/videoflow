<script lang="ts">
  import { onMount } from 'svelte';
  import { get, post } from '$lib/api';
  import { runBackgroundOp } from '$lib/ops';
  import { subscribeJobs } from '$lib/sse';
  import VideoPreview from '$lib/components/VideoPreview.svelte';
  import CaptionEditor from '$lib/components/CaptionEditor.svelte';
  import { Button } from '$lib/components/ui/button';
  import { Badge } from '$lib/components/ui/badge';
  import * as Dialog from '$lib/components/ui/dialog';
  import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '$lib/components/ui/table';
  import { toast } from 'svelte-sonner';
  import { Play, Captions, Clapperboard, Pencil, RefreshCw } from '@lucide/svelte';

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
  let captionDefaultStyle = $state('');
  // Effective style for an output: per-output pick, else the style-guide-derived default.
  const styleFor = (outId: string) =>
    captionStyle[outId] ?? (captionDefaultStyle || captionStyles[0] || 'kids');
  let captionStyle: Record<string, string> = $state({});
  let captionModel: Record<string, string> = $state({});
  let captionLanguage: Record<string, string> = $state({});
  // Captioning runs as a background op — per-output so several can run at once.
  let captioning: Record<string, boolean> = $state({});
  let retrying = $state('');
  // Caption editor dialog: the output being edited (lazy — the editor only
  // fetches when the dialog opens) plus its job id so we can refresh the row.
  let editingOutput = $state<{ jobId: string; out: any } | null>(null);

  async function refreshJobOutputs(jobId: string) {
    const detail = await get(`/render-jobs/${jobId}`);
    outputs[jobId] = detail.outputs;
    outputs = outputs;
  }


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
        captionDefaultStyle = cfg.default_style ?? '';
      })
      .catch(() => {
        // Fallback to legacy endpoint
        get('/caption-styles').then((s) => (captionStyles = s)).catch(() => {});
      });
    return subscribeJobs(
      () => refresh().catch(() => {}),
      () => refresh().catch(() => {})
    );
  });

  async function addCaptions(jobId: string, out: any) {
    captioning[out.id] = true;
    error = '';
    const lang = captionLanguage[out.id] ?? captionDefaultLanguage ?? 'zh';
    try {
      await runBackgroundOp(
        `/outputs/${out.id}/caption`,
        {
          style: styleFor(out.id),
          model: captionModel[out.id] ?? (captionDefaultModel || undefined),
          language: lang === 'auto' ? null : lang
        },
        {
          label: 'Captioning',
          onDone: async () => {
            captioning[out.id] = false;
            // Refetch the job detail so the output row picks up captioned_path.
            await refreshJobOutputs(jobId);
          },
          onFail: () => (captioning[out.id] = false)
        }
      );
    } catch (e: any) {
      captioning[out.id] = false;
      toast.error(e.message);
    }
  }

  async function fixAndRerender(out: any) {
    retrying = out.id;
    try {
      const res = await post(`/outputs/${out.id}/retry`);
      toast.success(`Corrective re-render started — job ${res.job_id}`);
      await refresh();
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      retrying = '';
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
                    {#if out.qa_json?.issues?.length}
                      <ul class="text-xs text-muted-foreground mt-0.5 max-w-56 space-y-0.5">
                        {#each out.qa_json.issues.slice(0, 3) as issue (issue)}
                          <li class="truncate" title={issue}>- {issue}</li>
                        {/each}
                      </ul>
                      <div class="mt-1">
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={!!retrying}
                          onclick={() => fixAndRerender(out)}
                        >
                          <RefreshCw class="size-3 mr-1 {retrying === out.id ? 'animate-spin' : ''}" />
                          {retrying === out.id ? 'submitting…' : 'Fix & re-render'}
                        </Button>
                      </div>
                    {/if}
                    <div class="flex flex-wrap items-center gap-1 mt-1">
                      {#if captionStyles.length}
                        <select
                          value={styleFor(out.id)}
                          onchange={(e) => (captionStyle[out.id] = (e.currentTarget as HTMLSelectElement).value)}
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
                        disabled={captioning[out.id]}
                        onclick={() => addCaptions(j.id, out)}
                      >
                        <Captions class="size-3 mr-1" />
                        {captioning[out.id] ? 'transcribing…' : out.captioned_path ? 'Re-caption' : 'Auto captions'}
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onclick={() => (editingOutput = { jobId: j.id, out })}
                      >
                        <Pencil class="size-3 mr-1" />Edit captions
                      </Button>
                      <Button variant="outline" size="sm" href={`/editor/${out.id}`}>
                        <Clapperboard class="size-3 mr-1" />Open in editor
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

  <Dialog.Root
    open={editingOutput !== null}
    onOpenChange={(open) => !open && (editingOutput = null)}
  >
    <Dialog.Content class="max-w-3xl sm:max-w-3xl">
      <Dialog.Header>
        <Dialog.Title>Edit captions</Dialog.Title>
        <Dialog.Description>
          Fix subtitle text and timing, then re-burn — no re-transcription.
        </Dialog.Description>
      </Dialog.Header>
      {#if editingOutput}
        {@const editing = editingOutput}
        <CaptionEditor
          outputId={editing.out.id}
          videoPath={editing.out.video_path}
          onsaved={() => refreshJobOutputs(editing.jobId).catch(() => {})}
        />
      {/if}
    </Dialog.Content>
  </Dialog.Root>
</div>
