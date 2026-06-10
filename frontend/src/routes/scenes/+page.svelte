<script lang="ts">
  import { onMount } from 'svelte';
  import { get, patch, post, mediaUrl } from '$lib/api';

  let scenes: any[] = [];
  let characters: any[] = [];
  let shotsByScene: Record<string, any[]> = {};
  let storyboards: Record<string, any> = {};
  let error = '';
  let busy = '';
  let ok = '';

  let idea = '';
  let targetDuration: number | '' = '';
  let castSelection: Record<string, string[]> = {};

  async function refresh() {
    [scenes, characters] = await Promise.all([get('/scenes'), get('/characters')]);
    const allAssets = await get('/assets');
    storyboards = {};
    for (const a of allAssets) {
      const sid = a.metadata_json?.scene_id;
      if (a.type === 'storyboard' && sid) storyboards[sid] = a;
    }
    await Promise.all(
      scenes.map(async (s) => {
        shotsByScene[s.id] = await get(`/scenes/${s.id}/shots`);
      })
    );
    shotsByScene = shotsByScene;
  }
  onMount(() => refresh().catch((e) => (error = e.message)));

  async function run(key: string, fn: () => Promise<unknown>, doneMsg = '') {
    busy = key;
    error = '';
    ok = '';
    try {
      await fn();
      await refresh();
      ok = doneMsg;
    } catch (e: any) {
      error = e.message;
    } finally {
      busy = '';
    }
  }

  const generateScript = () =>
    run(
      'script',
      () => post('/scripts/generate', { idea, target_duration: targetDuration || null }),
      'Script generated — scenes created below.'
    );

  const expandScene = (s: any) =>
    run(`expand-${s.id}`, () =>
      post(`/scenes/${s.id}/generate`, { character_ids: castSelection[s.id] ?? [] })
    );

  const generateShots = (s: any) =>
    run(`shots-${s.id}`, () => post(`/scenes/${s.id}/shots/generate`));

  const generateStoryboard = (s: any) =>
    run(`sb-${s.id}`, () => post(`/scenes/${s.id}/storyboard`), '分镜图 generated.');

  const renderScene = (s: any) =>
    run(
      `render-${s.id}`,
      () => post(`/scenes/${s.id}/render`),
      'Render job submitted — track it on the Render page.'
    );

  function toggleCast(sceneId: string, charId: string) {
    const cur = castSelection[sceneId] ?? [];
    castSelection[sceneId] = cur.includes(charId)
      ? cur.filter((c) => c !== charId)
      : [...cur, charId];
  }

  const saveScene = (s: any) =>
    run(`save-${s.id}`, () =>
      patch(`/scenes/${s.id}`, {
        title: s.title,
        summary: s.summary,
        duration: s.duration,
        aspect_ratio: s.aspect_ratio
      })
    , 'Scene saved.');

  const saveShot = (shot: any) =>
    run(`save-${shot.id}`, () =>
      patch(`/shots/${shot.id}`, {
        prompt: shot.prompt,
        duration: shot.duration,
        camera: shot.camera,
        movement: shot.movement
      })
    , 'Shot saved.');
</script>

<h1>Scenes</h1>

<form class="panel" on:submit|preventDefault={generateScript}>
  <label for="idea">Story idea → script + scenes</label>
  <textarea id="idea" bind:value={idea} placeholder="e.g. 中文识字短片：我是乐乐，乐乐是我…" />
  <div class="row">
    <div>
      <label for="dur">Target duration (s, optional)</label>
      <input id="dur" type="number" bind:value={targetDuration} min="3" />
    </div>
    <div><button disabled={busy === 'script' || !idea}>Generate script</button></div>
  </div>
  {#if error}<div class="error">{error}</div>{/if}
  {#if ok}<div class="ok">{ok}</div>{/if}
</form>

{#each scenes.slice().reverse() as s (s.id)}
  <div class="panel">
    <div class="row">
      <div style="flex:2">
        <label for="title-{s.id}">Title</label>
        <input id="title-{s.id}" bind:value={s.title} />
      </div>
      <div style="flex:0 0 90px;min-width:90px">
        <label for="dur-{s.id}">Duration</label>
        <input id="dur-{s.id}" type="number" min="3" bind:value={s.duration} />
      </div>
      <div style="flex:0 0 100px;min-width:100px">
        <label for="ar-{s.id}">Aspect</label>
        <select id="ar-{s.id}" bind:value={s.aspect_ratio}>
          <option>9:16</option><option>16:9</option><option>1:1</option>
        </select>
      </div>
      <div style="flex:0 0 auto;min-width:auto">
        <button class="small secondary" disabled={!!busy} on:click={() => saveScene(s)}>
          {busy === `save-${s.id}` ? '…' : 'Save scene'}
        </button>
      </div>
    </div>
    <label for="sum-{s.id}">Summary <span class="meta">({s.id})</span></label>
    <textarea id="sum-{s.id}" bind:value={s.summary} />


    <div class="meta">Cast for expansion:</div>
    {#each characters as c}
      <label style="display:inline-flex;align-items:center;gap:0.3rem;margin-right:1rem;">
        <input
          type="checkbox"
          style="width:auto"
          checked={(castSelection[s.id] ?? s.character_ids_json ?? []).includes(c.id)}
          on:change={() => toggleCast(s.id, c.id)}
        />
        {c.name}
      </label>
    {/each}

    <div>
      <button class="small secondary" disabled={!!busy} on:click={() => expandScene(s)}>
        {busy === `expand-${s.id}` ? '…' : '1. Expand scene (AI)'}
      </button>
      <button class="small secondary" disabled={!!busy} on:click={() => generateShots(s)}>
        {busy === `shots-${s.id}` ? '…' : '2. Generate shots (AI)'}
      </button>
      <button class="small secondary" disabled={!!busy || !(shotsByScene[s.id]?.length)} on:click={() => generateStoryboard(s)}>
        {busy === `sb-${s.id}` ? '…' : '3. Generate 分镜图 (ERNIE)'}
      </button>
      <button class="small" disabled={!!busy || !(shotsByScene[s.id]?.length)} on:click={() => renderScene(s)}>
        {busy === `render-${s.id}` ? '…' : '4. Render scene (Kling)'}
      </button>
    </div>

    {#if shotsByScene[s.id]?.length}
      <table style="margin-top:0.8rem">
        <thead><tr><th>#</th><th style="width:50%">prompt</th><th>camera</th><th>movement</th><th>s</th><th /></tr></thead>
        <tbody>
          {#each shotsByScene[s.id] as shot (shot.id)}
            <tr>
              <td>{shot.shot_order + 1}</td>
              <td><textarea style="min-height:46px" bind:value={shot.prompt} /></td>
              <td><input bind:value={shot.camera} /></td>
              <td><input bind:value={shot.movement} /></td>
              <td style="width:70px"><input type="number" min="1" max="15" bind:value={shot.duration} /></td>
              <td>
                <button class="small secondary" disabled={!!busy} on:click={() => saveShot(shot)}>
                  {busy === `save-${shot.id}` ? '…' : 'Save'}
                </button>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
      <div class="meta">
        Shot durations sum to {shotsByScene[s.id].reduce((t, sh) => t + (sh.duration || 0), 0)}s
        (Kling allows 3–15s per render).
      </div>
    {/if}

    {#if storyboards[s.id]}
      <h2>分镜图</h2>
      <img class="storyboard" src={mediaUrl(storyboards[s.id].file_path)} alt="分镜图" loading="lazy" />
    {/if}
  </div>
{/each}
