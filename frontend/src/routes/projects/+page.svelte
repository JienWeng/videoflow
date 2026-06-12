<script lang="ts">
  import { onMount } from 'svelte';
  import { get, post, patch, del } from '$lib/api';
  import { Button } from '$lib/components/ui/button';
  import { Badge } from '$lib/components/ui/badge';
  import { Card, CardContent } from '$lib/components/ui/card';
  import { Input } from '$lib/components/ui/input';
  import { Skeleton } from '$lib/components/ui/skeleton';
  import * as Dialog from '$lib/components/ui/dialog';
  import { toast } from 'svelte-sonner';
  import { FolderPlus, Pencil, Trash2, Check, X } from '@lucide/svelte';

  let projects: any[] = $state([]);
  let loaded = $state(false);
  let busy = $state('');

  let name = $state('');
  let description = $state('');

  let renamingId = $state('');
  let renameValue = $state('');

  let deleteTarget: any = $state(null);

  async function refresh() {
    projects = await get('/projects');
  }
  onMount(() =>
    refresh()
      .catch((e) => toast.error(e.message))
      .finally(() => (loaded = true))
  );

  async function run(key: string, fn: () => Promise<unknown>) {
    busy = key;
    try {
      await fn();
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      busy = '';
    }
  }

  // The active project transparently scopes every backend endpoint. After
  // creating or switching, we do a full page reload to the Studio so every
  // page refetches its data under the new project scope.
  const createProject = (e: Event) => {
    e.preventDefault();
    run('create', async () => {
      await post('/projects', { name, description });
      window.location.href = '/';
    });
  };

  const activate = (p: any) =>
    run(`open-${p.id}`, async () => {
      await post(`/projects/${p.id}/activate`);
      window.location.href = '/';
    });

  function startRename(p: any) {
    renamingId = p.id;
    renameValue = p.name;
  }

  const saveRename = (p: any) =>
    run(`rename-${p.id}`, async () => {
      await patch(`/projects/${p.id}`, { name: renameValue });
      renamingId = '';
      await refresh();
    });

  const deleteProject = (p: any) =>
    run(`delete-${p.id}`, async () => {
      await del(`/projects/${p.id}`);
      deleteTarget = null;
      await refresh();
    });

  function countsLine(c: any): string {
    const parts = [
      `${c?.scenes ?? 0} scenes`,
      `${c?.characters ?? 0} characters`,
      `${c?.assets ?? 0} assets`
    ];
    return parts.join(' · ');
  }

  const fmtDate = (s: string) =>
    new Date(s).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
</script>

<div class="p-6">
  <div class="mb-4">
    <h1 class="text-lg font-semibold">Projects</h1>
    <p class="text-sm text-muted-foreground">
      Each project is a separate workspace — its own scenes, characters, assets and renders.
    </p>
  </div>

  <form class="mb-6 rounded-lg border border-border bg-card p-4" onsubmit={createProject}>
    <div class="flex flex-wrap gap-4 items-end">
      <div class="flex-1 min-w-[160px]">
        <label class="block text-xs text-muted-foreground mb-1" for="proj-name">Name</label>
        <Input id="proj-name" bind:value={name} required placeholder="My new video" />
      </div>
      <div class="flex-1 min-w-[160px]">
        <label class="block text-xs text-muted-foreground mb-1" for="proj-desc">Description (optional)</label>
        <Input id="proj-desc" bind:value={description} />
      </div>
      <div>
        <Button type="submit" size="sm" disabled={busy === 'create' || !name}>
          <FolderPlus class="size-4 mr-1" />Create project
        </Button>
      </div>
    </div>
    <p class="mt-2 text-xs text-muted-foreground">Creating switches you to the new project.</p>
  </form>

  {#if !loaded}
    <div class="grid grid-cols-[repeat(auto-fill,minmax(280px,1fr))] gap-4">
      {#each Array(2) as _, i (i)}
        <div class="rounded-lg border border-border p-4 space-y-2">
          <Skeleton class="h-4 w-32" />
          <Skeleton class="h-3 w-48" />
          <Skeleton class="h-3 w-40" />
        </div>
      {/each}
    </div>
  {:else}
    <div class="grid grid-cols-[repeat(auto-fill,minmax(280px,1fr))] gap-4">
      {#each projects as p (p.id)}
        <Card>
          <CardContent class="p-4">
            <div class="flex items-start justify-between gap-2 mb-1">
              {#if renamingId === p.id}
                <form
                  class="flex items-center gap-1 flex-1"
                  onsubmit={(e) => {
                    e.preventDefault();
                    saveRename(p);
                  }}
                >
                  <Input class="h-7 text-sm" bind:value={renameValue} required />
                  <Button type="submit" size="icon" variant="ghost" class="size-7 shrink-0"
                    disabled={!!busy || !renameValue} title="Save name">
                    <Check class="size-3.5" />
                  </Button>
                  <Button type="button" size="icon" variant="ghost" class="size-7 shrink-0"
                    onclick={() => (renamingId = '')} title="Cancel">
                    <X class="size-3.5" />
                  </Button>
                </form>
              {:else}
                <div class="flex items-center gap-1.5 min-w-0">
                  <span class="font-semibold text-sm truncate">{p.name}</span>
                  <button
                    class="text-muted-foreground hover:text-foreground shrink-0"
                    title="Rename project"
                    onclick={() => startRename(p)}
                  >
                    <Pencil class="size-3" />
                  </button>
                </div>
                {#if p.is_active}
                  <Badge>Active</Badge>
                {/if}
              {/if}
            </div>
            {#if p.description}
              <p class="text-sm text-muted-foreground mb-1">{p.description}</p>
            {/if}
            <p class="text-xs text-muted-foreground mb-0.5">{countsLine(p.counts)}</p>
            <p class="text-xs text-muted-foreground mb-3">Created {fmtDate(p.created_at)}</p>
            <div class="flex gap-1.5">
              {#if !p.is_active}
                <Button variant="secondary" size="sm" disabled={!!busy} onclick={() => activate(p)}>
                  {busy === `open-${p.id}` ? 'Opening…' : 'Open'}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  class="text-destructive hover:text-destructive"
                  disabled={!!busy}
                  onclick={() => (deleteTarget = p)}
                >
                  <Trash2 class="size-3.5 mr-1" />Delete
                </Button>
              {/if}
            </div>
          </CardContent>
        </Card>
      {/each}
    </div>
  {/if}

  <Dialog.Root open={deleteTarget !== null} onOpenChange={(open) => !open && (deleteTarget = null)}>
    <Dialog.Content>
      <Dialog.Header>
        <Dialog.Title>Delete "{deleteTarget?.name}"?</Dialog.Title>
        <Dialog.Description>
          Deletes ALL its scenes, characters, assets and renders. Files on disk are kept.
        </Dialog.Description>
      </Dialog.Header>
      <Dialog.Footer>
        <Button variant="outline" onclick={() => (deleteTarget = null)}>Cancel</Button>
        <Button variant="destructive" disabled={!!busy} onclick={() => deleteProject(deleteTarget)}>
          <Trash2 class="size-4 mr-1" />Delete project
        </Button>
      </Dialog.Footer>
    </Dialog.Content>
  </Dialog.Root>
</div>
