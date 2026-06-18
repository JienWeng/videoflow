<script lang="ts">
  import { mediaUrl } from '$lib/api';
  import MentionTextarea from '$lib/components/MentionTextarea.svelte';
  import { Button } from '$lib/components/ui/button';
  import { Badge } from '$lib/components/ui/badge';
  import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '$lib/components/ui/table';
  import {
    Wand2, Save, LayoutGrid, Video, Images, Trash2, Sparkles, ImagePlus,
    Lightbulb, VolumeX, Check, Maximize2, Clock, Film, Plus, ChevronUp, ChevronDown
  } from '@lucide/svelte';

  // The full detail of the selected scene. The parent owns all state + handlers
  // (keyed maps shared with the list); we bind into them so nothing is lost.
  let {
    s,
    steps,
    characters,
    style,
    busy,
    opBusy,
    sceneDirty = false,
    shotDirty = (_sh: any) => false,
    storyboard = null,
    shots = [],
    // bindable per-scene state maps
    castSelection = $bindable(),
    sceneRefine = $bindable(),
    shotRefine = $bindable(),
    autoProps = $bindable(),
    assetInstr = $bindable(),
    assetMax = $bindable(),
    generatedAssets = $bindable(),
    assetPlans = $bindable(),
    planSelected = $bindable(),
    // handlers
    onExpand,
    onSave,
    onRefineScene,
    onToggleCast,
    onGenerateShots,
    onAddShot,
    onMoveShot,
    onSaveShot,
    onRefineShot,
    onDeleteShot,
    onSuggestAssets,
    onGenerateAssets,
    onGenerateSelectedAssets,
    onGenerateStoryboard,
    onRenderScene,
    onDelete,
    onLightbox
  }: any = $props();

  // Same correct-CTA logic as the old card: the "current" step is the first
  // not-done one ONLY when nothing after it is done; otherwise it's complete-ish
  // (primary CTA → Re-render, skipped earlier steps shown muted but clickable).
  const firstNotDone = $derived(steps.findIndex((st: any) => !st.done));
  const laterDone = $derived(
    firstNotDone !== -1 && steps.some((st: any, i: number) => i > firstNotDone && st.done)
  );
  const currentIdx = $derived(laterDone ? -1 : firstNotDone);
  const current = $derived(currentIdx === -1 ? null : steps[currentIdx]);
</script>

<div class="p-5">
  <!-- Header: title, duration, primary next-step CTA / re-render, delete -->
  <div class="flex items-start gap-4">
    {#if storyboard}
      <button type="button"
        class="group relative size-16 shrink-0 overflow-hidden rounded-lg border border-border focus:outline-none focus:ring-2 focus:ring-ring"
        title="View storyboard" onclick={() => onLightbox(storyboard)}>
        <img class="size-full object-cover transition-transform group-hover:scale-105"
          src={mediaUrl(storyboard.file_path)} alt="Storyboard" loading="lazy" />
        <span class="absolute inset-0 flex items-center justify-center bg-black/0 group-hover:bg-black/40 transition-colors">
          <Maximize2 class="size-4 text-white opacity-0 group-hover:opacity-100 transition-opacity" />
        </span>
      </button>
    {:else}
      <div class="flex size-16 shrink-0 items-center justify-center rounded-lg border border-dashed border-border bg-muted/30 text-muted-foreground/50">
        <Film class="size-5" />
      </div>
    {/if}

    <div class="min-w-0 flex-1">
      <div class="flex items-center gap-2 mb-2">
        <h2 class="font-semibold text-base truncate" title={s.title}>{s.title || 'Untitled scene'}</h2>
        <Badge variant="secondary" class="shrink-0 gap-1"><Clock class="size-3" />{s.duration}s</Badge>
        {#if sceneDirty}
          <Badge variant="outline" class="shrink-0 border-amber-500/50 text-amber-600">Unsaved</Badge>
        {/if}
        <span class="ml-auto font-mono text-[10px] text-muted-foreground/40">{s.id}</span>
      </div>

      <!-- Pipeline stepper: connected segments, primary visual element -->
      <div class="flex items-center gap-0 flex-wrap">
        {#each steps as st, i (st.key)}
          {#if i > 0}
            <div class="h-0.5 w-4 sm:w-6 shrink-0 {st.done && steps[i - 1].done ? 'bg-primary/50' : 'bg-border'}"></div>
          {/if}
          {#if st.done}
            <span class="inline-flex items-center gap-1.5 rounded-full bg-primary/10 px-2.5 py-1 text-xs font-medium text-primary">
              <Check class="size-3" />{st.label}{#if st.key === 'shots' && shots?.length}<span class="opacity-70">{shots.length}</span>{/if}
            </span>
          {:else if i === currentIdx}
            <button type="button"
              class="inline-flex items-center gap-1.5 rounded-full bg-background px-2.5 py-1 text-xs font-medium ring-2 ring-primary/70 hover:bg-accent disabled:opacity-60"
              disabled={st.busy} onclick={st.action}>
              <st.icon class="size-3" />{st.busy ? st.busyLabel : st.label}
            </button>
          {:else if !st.done && laterDone}
            <button type="button"
              class="inline-flex items-center gap-1.5 rounded-full border border-dashed border-border px-2.5 py-1 text-xs text-muted-foreground/60 hover:text-foreground disabled:opacity-60"
              title="Skipped — later steps are already done. Click to run it anyway."
              disabled={st.busy} onclick={st.action}>
              <st.icon class="size-3" />{st.busy ? st.busyLabel : st.label}
            </button>
          {:else}
            <span class="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs text-muted-foreground/50">
              <st.icon class="size-3" />{st.label}
            </span>
          {/if}
        {/each}
      </div>
    </div>

    <div class="flex shrink-0 items-center gap-2">
      {#if current}
        <div class="flex flex-col items-end gap-1">
          <Button size="sm" disabled={current.busy} onclick={current.action}>
            <current.icon class="size-3.5 mr-1" />
            {current.busy ? current.busyLabel : `Next: ${current.label}`}
          </Button>
          {#if current.key === 'shots'}
            <label class="inline-flex items-center gap-1 text-xs text-muted-foreground cursor-pointer select-none">
              <input
                type="checkbox"
                class="w-auto"
                checked={autoProps[s.id] ?? true}
                onchange={(e) => (autoProps[s.id] = (e.currentTarget as HTMLInputElement).checked)}
              />
              auto props
            </label>
          {/if}
        </div>
      {:else}
        <Button variant="secondary" size="sm" disabled={busy[`render-${s.id}`]} onclick={() => onRenderScene(s)}>
          <Video class="size-3.5 mr-1" />{busy[`render-${s.id}`] ? 'Submitting…' : 'Re-render'}
        </Button>
      {/if}
      <Button variant="ghost" size="icon" class="size-8 text-muted-foreground hover:text-destructive"
        title="Delete scene" disabled={busy[`delete-${s.id}`]} onclick={() => onDelete(s)}>
        <Trash2 class="size-4" />
      </Button>
    </div>
  </div>

  <div class="mt-5 space-y-5">
    <!-- Scene -->
    <div>
      <div class="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">Scene</div>
      <div class="flex flex-wrap gap-4 items-end mb-2">
        <div style="flex:2;min-width:160px">
          <label class="block text-xs text-muted-foreground mb-1" for="title-{s.id}">Title</label>
          <input id="title-{s.id}" bind:value={s.title}
            class="w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm" />
        </div>
        <div style="flex:0 0 90px;min-width:90px">
          <label class="block text-xs text-muted-foreground mb-1" for="dur-{s.id}">Duration</label>
          <input id="dur-{s.id}" type="number" min="3" bind:value={s.duration}
            class="w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm" />
        </div>
        <div style="flex:0 0 100px;min-width:100px">
          <label class="block text-xs text-muted-foreground mb-1" for="ar-{s.id}">Aspect</label>
          <select id="ar-{s.id}" bind:value={s.aspect_ratio}
            class="w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm">
            <option>9:16</option><option>16:9</option><option>1:1</option>
          </select>
        </div>
        <div>
          <Button variant={sceneDirty ? 'default' : 'secondary'} size="sm"
            disabled={busy[`save-${s.id}`] || !sceneDirty} onclick={() => onSave(s)}>
            <Save class="size-3 mr-1" />{busy[`save-${s.id}`] ? 'Saving…' : sceneDirty ? 'Save scene *' : 'Saved'}
          </Button>
        </div>
      </div>

      <label class="block text-xs text-muted-foreground mb-1" for="sum-{s.id}">Summary</label>
      <MentionTextarea id="sum-{s.id}" bind:value={s.summary}
        class="w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm min-h-[70px] resize-y mb-3" />

      <div class="flex gap-2 mb-3">
        <input
          bind:value={sceneRefine[s.id]}
          placeholder="Tell AI what to change…"
          class="flex-1 rounded-md border border-input bg-background px-2 py-1.5 text-sm"
        />
        <Button variant="outline" size="sm"
          disabled={busy[`refine-${s.id}`] || !(sceneRefine[s.id] ?? '').trim()} onclick={() => onRefineScene(s)}>
          <Sparkles class="size-3 mr-1" />{busy[`refine-${s.id}`] ? 'Refining…' : 'AI refine'}
        </Button>
      </div>

      <div class="text-xs text-muted-foreground mb-1">Cast for expansion:</div>
      <div class="flex flex-wrap gap-3 mb-2">
        {#each characters as c}
          <label class="inline-flex items-center gap-1.5 text-sm cursor-pointer">
            <input
              type="checkbox"
              class="w-auto"
              checked={(castSelection[s.id] ?? s.character_ids_json ?? []).includes(c.id)}
              onchange={() => onToggleCast(s.id, c.id)}
            />
            {c.name}
          </label>
        {/each}
      </div>
      <Button variant="outline" size="sm" disabled={busy[`expand-${s.id}`]} onclick={() => onExpand(s)}>
        <Wand2 class="size-3 mr-1" />{busy[`expand-${s.id}`] ? 'Expanding…' : 'Re-expand scene (AI)'}
      </Button>
    </div>

    <!-- Shots -->
    <div class="border-t border-border pt-4">
      <div class="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">Shots</div>
      <div class="flex flex-wrap items-center gap-2 mb-2">
        <Button variant="outline" size="sm" disabled={opBusy[`shots-${s.id}`]} onclick={() => onGenerateShots(s)}>
          <LayoutGrid class="size-3 mr-1" />{opBusy[`shots-${s.id}`] ? 'Generating…' : 'Regenerate shots (AI)'}
        </Button>
        <Button variant="outline" size="sm" disabled={busy[`add-${s.id}`]} onclick={() => onAddShot(s)}>
          <Plus class="size-3 mr-1" />{busy[`add-${s.id}`] ? 'Adding…' : 'Add shot'}
        </Button>
        <label class="inline-flex items-center gap-1 text-xs text-muted-foreground cursor-pointer select-none">
          <input
            type="checkbox"
            class="w-auto"
            checked={autoProps[s.id] ?? true}
            onchange={(e) => (autoProps[s.id] = (e.currentTarget as HTMLInputElement).checked)}
          />
          auto props
        </label>
      </div>

      {#if shots?.length}
        <div class="flex gap-2 items-center">
          <Sparkles class="size-3.5 text-muted-foreground shrink-0" />
          <input
            bind:value={shotRefine[s.id]}
            placeholder="Shot refine instruction — then click the sparkles on a shot row…"
            class="flex-1 rounded-md border border-input bg-background px-2 py-1.5 text-xs"
          />
        </div>
        <div class="mt-2 overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead class="w-16">#</TableHead>
                <TableHead class="w-1/2">prompt</TableHead>
                <TableHead>camera</TableHead>
                <TableHead>movement</TableHead>
                <TableHead class="w-16">s</TableHead>
                <TableHead></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {#each shots as shot, i (shot.id)}
                <TableRow>
                  <TableCell>
                    <div class="flex items-center gap-0.5">
                      <span class="w-4 text-right">{shot.shot_order + 1}</span>
                      <div class="flex flex-col">
                        <button type="button" title="Move up"
                          class="text-muted-foreground/60 hover:text-foreground disabled:opacity-30"
                          disabled={i === 0 || busy[`reorder-${s.id}`]}
                          onclick={() => onMoveShot(s, shot, -1)}>
                          <ChevronUp class="size-3" />
                        </button>
                        <button type="button" title="Move down"
                          class="text-muted-foreground/60 hover:text-foreground disabled:opacity-30"
                          disabled={i === shots.length - 1 || busy[`reorder-${s.id}`]}
                          onclick={() => onMoveShot(s, shot, 1)}>
                          <ChevronDown class="size-3" />
                        </button>
                      </div>
                    </div>
                  </TableCell>
                  <TableCell>
                    <div class="relative">
                      <MentionTextarea class="w-full rounded border border-input bg-background px-2 py-1 text-xs min-h-[46px] resize-y"
                        bind:value={shot.prompt} />
                      {#if !/「[^」]+」/.test(shot.prompt ?? '')}
                        <VolumeX
                          class="absolute top-1 right-1 size-3.5 text-muted-foreground/60 pointer-events-none"
                          title="No spoken line — every shot should speak"
                        />
                      {/if}
                    </div>
                  </TableCell>
                  <TableCell>
                    <input class="w-full rounded border border-input bg-background px-2 py-1 text-xs"
                      bind:value={shot.camera} />
                  </TableCell>
                  <TableCell>
                    <input class="w-full rounded border border-input bg-background px-2 py-1 text-xs"
                      bind:value={shot.movement} />
                  </TableCell>
                  <TableCell>
                    <input type="number" min="1" max="15"
                      class="w-16 rounded border border-input bg-background px-2 py-1 text-xs"
                      bind:value={shot.duration} />
                  </TableCell>
                  <TableCell>
                    <div class="flex items-center gap-0.5">
                      <Button variant={shotDirty(shot) ? 'default' : 'outline'} size="sm"
                        disabled={busy[`save-${shot.id}`] || !shotDirty(shot)} onclick={() => onSaveShot(shot)}>
                        {busy[`save-${shot.id}`] ? 'Saving…' : shotDirty(shot) ? 'Save *' : 'Saved'}
                      </Button>
                      <Button variant="ghost" size="icon" class="size-7" title="AI refine this shot"
                        disabled={busy[`refine-${shot.id}`] || !(shotRefine[s.id] ?? '').trim()} onclick={() => onRefineShot(s, shot)}>
                        <Sparkles class="size-3.5" />
                      </Button>
                      <Button variant="ghost" size="icon" class="size-7 text-destructive hover:text-destructive"
                        title="Delete shot" disabled={busy[`delete-${shot.id}`]} onclick={() => onDeleteShot(s, shot)}>
                        <Trash2 class="size-3.5" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              {/each}
            </TableBody>
          </Table>
        </div>
        <div class="text-xs text-muted-foreground mt-1">
          Shot durations sum to {shots.reduce((t: number, sh: any) => t + (sh.duration || 0), 0)}s
          (3–15s per render).
        </div>
      {:else}
        <p class="text-xs text-muted-foreground">No shots yet — generate them with AI, or add one manually.</p>
      {/if}
    </div>

    <!-- Assets -->
    <div class="border-t border-border pt-4">
      <div class="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">Assets</div>
      <div class="text-xs text-muted-foreground mb-1">Generate assets (props) for this scene:</div>
      <div class="flex flex-wrap gap-2 items-center">
        <input
          bind:value={assetInstr[s.id]}
          placeholder="e.g. 需要一个红色杯子 / a red cup"
          class="flex-1 min-w-[200px] rounded-md border border-input bg-background px-2 py-1.5 text-sm"
        />
        <input type="number" min="1" max="8" title="Max assets"
          value={assetMax[s.id] ?? 4}
          onchange={(e) => (assetMax[s.id] = Number((e.currentTarget as HTMLInputElement).value) || 4)}
          class="w-16 rounded-md border border-input bg-background px-2 py-1.5 text-sm"
        />
        <Button variant="outline" size="sm" disabled={busy[`plan-${s.id}`]} onclick={() => onSuggestAssets(s)}>
          <Lightbulb class="size-3 mr-1" />{busy[`plan-${s.id}`] ? 'Suggesting…' : 'Suggest'}
        </Button>
        <Button variant="outline" size="sm" disabled={opBusy[`assets-${s.id}`]} onclick={() => onGenerateAssets(s)}>
          <ImagePlus class="size-3 mr-1" />{opBusy[`assets-${s.id}`] ? 'Generating…' : 'Generate assets'}
        </Button>
        {#if style?.style_prompt}
          <Badge variant="secondary" class="text-muted-foreground max-w-[260px]" title={style.style_prompt}>
            <span class="truncate">
              styled: {style.style_prompt.length > 30
                ? `${style.style_prompt.slice(0, 30)}…`
                : style.style_prompt}
            </span>
          </Badge>
        {/if}
      </div>
      {#if assetPlans[s.id]?.assets?.length}
        {@const plan = assetPlans[s.id]!}
        {@const selectedItems = plan.assets.filter((_: any, i: number) => planSelected[s.id]?.[i])}
        {@const reuseCount = selectedItems.filter((a: any) => a.reuse).length}
        {@const genCount = selectedItems.length - reuseCount}
        <div class="mt-2 rounded-md border border-border p-2 space-y-2">
          <div class="text-xs font-medium">Suggested assets</div>
          <div class="flex flex-wrap gap-2">
            {#each plan.assets as a, i (i)}
              <label class="flex w-[230px] cursor-pointer items-start gap-2 rounded-md border border-border p-2 text-xs">
                <input type="checkbox" class="mt-0.5 w-auto" bind:checked={planSelected[s.id][i]} />
                <span class="min-w-0">
                  <span class="flex items-center gap-1.5">
                    <span class="font-medium truncate">{a.name}</span>
                    <Badge variant="secondary" class="text-[10px] px-1.5 py-0">{a.asset_type}</Badge>
                    {#if a.reuse}
                      <Badge variant="secondary" class="text-[10px] px-1.5 py-0 text-muted-foreground">reuses existing</Badge>
                    {/if}
                  </span>
                  <span class="block text-muted-foreground mt-0.5">{a.description}</span>
                  {#if a.shot_orders?.length}
                    <span class="block text-muted-foreground mt-0.5">
                      shots {a.shot_orders.map((o: number) => `#${o + 1}`).join(', ')}
                    </span>
                  {/if}
                </span>
              </label>
            {/each}
          </div>
          {#if plan.reasoning}
            <p class="text-xs text-muted-foreground">{plan.reasoning}</p>
          {/if}
          <Button size="sm" disabled={opBusy[`assets-${s.id}`] || !selectedItems.length}
            onclick={() => onGenerateSelectedAssets(s)}>
            <ImagePlus class="size-3 mr-1" />
            {opBusy[`assets-${s.id}`]
              ? 'Generating…'
              : reuseCount
                ? `Generate ${genCount} + reuse ${reuseCount}`
                : `Generate selected (${genCount})`}
          </Button>
        </div>
      {/if}
      {#if generatedAssets[s.id]?.length}
        <div class="flex flex-wrap gap-2 mt-2">
          {#each generatedAssets[s.id] as a (a.id)}
            <div class="w-[120px]">
              {#if mediaUrl(a.file_path)}
                <img class="w-full aspect-square object-cover rounded-md border border-border"
                  src={mediaUrl(a.file_path)} alt={a.name} loading="lazy" />
              {/if}
              <div class="text-xs text-muted-foreground truncate mt-0.5" title={a.name}>{a.name}</div>
            </div>
          {/each}
        </div>
      {/if}
    </div>

    <!-- Storyboard -->
    <div class="border-t border-border pt-4">
      <div class="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">Storyboard</div>
      <div class="flex flex-wrap items-center gap-2 mb-2">
        <Button variant="outline" size="sm"
          disabled={opBusy[`sb-${s.id}`] || !(shots?.length)}
          onclick={() => onGenerateStoryboard(s)}>
          <Images class="size-3 mr-1" />{opBusy[`sb-${s.id}`] ? 'Generating…' : 'Regenerate storyboard'}
        </Button>
      </div>
      {#if storyboard}
        <button type="button"
          class="group relative block max-w-[420px] w-full overflow-hidden rounded-lg border border-border focus:outline-none focus:ring-2 focus:ring-ring"
          title="Click to enlarge" onclick={() => onLightbox(storyboard)}>
          <img class="w-full transition-transform group-hover:scale-[1.02]" src={mediaUrl(storyboard.file_path)} alt="Storyboard" loading="lazy" />
          <span class="absolute right-2 top-2 flex items-center gap-1 rounded-md bg-black/60 px-2 py-1 text-xs text-white opacity-0 group-hover:opacity-100 transition-opacity">
            <Maximize2 class="size-3" />Enlarge
          </span>
        </button>
      {:else}
        <p class="text-xs text-muted-foreground">No storyboard yet.</p>
      {/if}
    </div>
  </div>
</div>
