<script lang="ts">
  import { preventDefault } from 'svelte/legacy';

  import { onDestroy, onMount } from 'svelte';
  import { get, post } from '$lib/api';
  import VideoPreview from '$lib/components/VideoPreview.svelte';

  let jobs: any[] = $state([]);
  let scenes: any[] = $state([]);
  let shots: any[] = $state([]);
  let outputs: Record<string, any[]> = $state({});
  let error = $state('');
  let busy = $state(false);

  let sceneId = $state('');
  let shotId = $state('');
  let captionStyles: string[] = $state([]);
  let captionStyle: Record<string, string> = $state({});
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
    get('/caption-styles').then((s) => (captionStyles = s)).catch(() => {});
    timer = setInterval(() => refresh().catch(() => {}), 5000);
  });
  onDestroy(() => clearInterval(timer));

  async function addCaptions(jobId: string, out: any) {
    captioning = out.id;
    error = '';
    try {
      const updated = await post(`/outputs/${out.id}/caption`, {
        style: captionStyle[out.id] ?? 'kids'
      });
      outputs[jobId] = outputs[jobId].map((o) => (o.id === out.id ? updated : o));
      outputs = outputs;
    } catch (e: any) {
      error = e.message;
    } finally {
      captioning = '';
    }
  }

  async function loadShots() {
    shots = sceneId ? await get(`/scenes/${sceneId}/shots`) : [];
    shotId = '';
  }

  async function renderFromShot() {
    busy = true;
    error = '';
    try {
      await post('/render/from-shot', { scene_id: sceneId, shot_id: shotId });
      await refresh();
    } catch (e: any) {
      error = e.message;
    } finally {
      busy = false;
    }
  }
</script>

<h1>Render</h1>

<form class="panel" onsubmit={preventDefault(renderFromShot)}>
  <div class="row">
    <div>
      <label for="scene">Scene</label>
      <select id="scene" bind:value={sceneId} onchange={loadShots}>
        <option value="">choose…</option>
        {#each scenes as s}<option value={s.id}>{s.title}</option>{/each}
      </select>
    </div>
    <div>
      <label for="shot">Shot (prompt-agent render)</label>
      <select id="shot" bind:value={shotId} disabled={!shots.length}>
        <option value="">choose…</option>
        {#each shots as sh}<option value={sh.id}>#{sh.shot_order + 1} {sh.prompt.slice(0, 50)}</option>{/each}
      </select>
    </div>
    <div>
      <button disabled={busy || !shotId}>Render shot</button>
    </div>
  </div>
  <div class="meta">Whole-scene multi-shot renders live on the Scenes page (step 4).</div>
  {#if error}<div class="error">{error}</div>{/if}
</form>

<table>
  <thead>
    <tr><th>job</th><th>scene / shot</th><th>model</th><th>status</th><th>error</th></tr>
  </thead>
  <tbody>
    {#each jobs.slice().reverse() as j (j.id)}
      <tr>
        <td>{j.id}</td>
        <td>{j.scene_id}{j.shot_id ? ` / ${j.shot_id}` : ''}</td>
        <td>{j.model?.split('/').slice(-2).join('/')}</td>
        <td><span class="status {j.status}">{j.status}</span></td>
        <td class="meta">{j.error ?? ''}</td>
      </tr>
      {#if outputs[j.id]?.length}
        <tr>
          <td colspan="5">
            <div class="row">
              {#each outputs[j.id] as out (out.id)}
                <div style="flex:0 0 auto">
                  <VideoPreview path={out.captioned_path || out.video_path} />
                  <div class="meta">
                    QA: {out.score ?? '—'} {out.qa_json?.recommendation ?? ''}
                    {#if out.captioned_path}· <span class="status succeeded">captioned</span>{/if}
                  </div>
                  <div class="row" style="align-items:center;gap:0.4rem">
                    <select style="flex:0 0 110px;min-width:110px" bind:value={captionStyle[out.id]}>
                      {#each captionStyles as st}<option value={st}>{st}</option>{/each}
                    </select>
                    <button
                      class="small secondary"
                      style="flex:0 0 auto;min-width:auto"
                      disabled={!!captioning}
                      onclick={() => addCaptions(j.id, out)}
                    >
                      {captioning === out.id ? 'transcribing…' : out.captioned_path ? 'Re-caption' : 'Auto captions'}
                    </button>
                  </div>
                </div>
              {/each}
            </div>
          </td>
        </tr>
      {/if}
    {/each}
  </tbody>
</table>
