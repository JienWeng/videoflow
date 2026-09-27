<script lang="ts">
  import '../app.css';
  import { page } from '$app/state';
  import { onMount } from 'svelte';
  import {
    Clapperboard,
    Image,
    Users,
    ListVideo,
    Film,
    FolderOpen,
    SlidersHorizontal
  } from '@lucide/svelte';
  import { Toaster } from '$lib/components/ui/sonner';
  import ActivityTray from '$lib/components/ActivityTray.svelte';
  import CommandPalette from '$lib/shell/CommandPalette.svelte';
  import { palette } from '$lib/shell/palette.svelte';
  import { initActivity } from '$lib/activity.svelte';
  import { get } from '$lib/api';
  import { watchTheme } from '$lib/shell/theme';

  let { children } = $props();

  // The active project scopes every backend endpoint; switching does a full
  // page reload (see /projects), so fetching once on mount is always fresh.
  let activeProject: any = $state(null);

  onMount(() => {
    initActivity();
    // ModeWatcher-style: keep <html> in sync with the saved theme preference
    // (the Settings appearance toggle writes localStorage['videoflow.theme']).
    // app.html applied the initial value pre-paint; this reacts to changes.
    const stopTheme = watchTheme();
    return stopTheme;
  });

  $effect(() => {
    // SvelteKit soft navigation reuses the root layout after project activation.
    const path = page.url.pathname;
    void path;
    get('/projects/active').then((p) => (activeProject = p)).catch(() => {});
  });

  const createNav = [{ href: '/create', label: 'Create video', icon: Clapperboard }];

  const outputNav = [{ href: '/render', label: 'My videos', icon: Film }];

  const advancedNav = [
    { href: '/', label: 'Studio', icon: Clapperboard },
    { href: '/scenes', label: 'Scenes', icon: ListVideo },
    { href: '/characters', label: 'Characters', icon: Users },
    { href: '/assets', label: 'Assets', icon: Image }
  ];

  const systemNav = [{ href: '/settings', label: 'Settings', icon: SlidersHorizontal }];

  // The editor is contextual (reached from a render output), so it highlights Render.
  function isActive(href: string, pathname: string): boolean {
    if (href === '/') return pathname === '/';
    if (href === '/render') return pathname.startsWith('/render') || pathname.startsWith('/editor');
    return pathname.startsWith(href);
  }

  // App-wide Cmd/Ctrl+K. Hoisted here (not the Studio page) so the palette is
  // reachable from every route — onboarding promises "press Ctrl/⌘ K anytime".
  function onKeydown(e: KeyboardEvent) {
    if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K')) {
      e.preventDefault();
      palette.toggle();
    }
  }
</script>

<div class="flex h-screen min-w-0 flex-col bg-background text-foreground md:flex-row">
  <nav aria-label="Primary" class="flex shrink-0 items-center gap-1 overflow-x-auto border-b border-border px-2 py-1.5 md:hidden">
    <a class="shrink-0 rounded-md px-2 py-1.5 text-xs font-medium hover:bg-accent" href="/projects" title={activeProject?.name ?? 'Projects'}>{activeProject?.name ?? 'Projects'}</a>
    <a class="shrink-0 rounded-md px-2 py-1.5 text-xs hover:bg-accent" href="/create">Create</a>
    <a class="shrink-0 rounded-md px-2 py-1.5 text-xs hover:bg-accent" href="/render">Videos</a>
    <a class="shrink-0 rounded-md px-2 py-1.5 text-xs hover:bg-accent" href="/">Studio</a>
    <a class="shrink-0 rounded-md px-2 py-1.5 text-xs hover:bg-accent" href="/scenes">Scenes</a>
    <a class="shrink-0 rounded-md px-2 py-1.5 text-xs hover:bg-accent" href="/characters">Characters</a>
    <a class="shrink-0 rounded-md px-2 py-1.5 text-xs hover:bg-accent" href="/assets">Assets</a>
    <a class="shrink-0 rounded-md px-2 py-1.5 text-xs hover:bg-accent" href="/settings">Settings</a>
  </nav>
  <aside class="hidden w-48 shrink-0 flex-col border-r border-border p-3 md:flex">
    <div class="px-2 pt-3 pb-1 text-sm font-semibold tracking-wide">VideoFlow</div>
    <!-- Current-project row: the entry point to /projects (switch, create, manage). -->
    <a
      href="/projects"
      title={activeProject ? `Project: ${activeProject.name}` : 'Projects'}
      class="mb-1 flex items-center gap-2 rounded-md px-2 py-1.5 text-xs hover:bg-accent
             {page.url.pathname.startsWith('/projects') ? 'bg-accent font-medium' : 'text-muted-foreground'}"
    >
      <FolderOpen class="size-3.5 shrink-0" />
      <span class="truncate">{activeProject?.name ?? 'Projects'}</span>
    </a>

    <!-- Primary creation path -->
    <div class="px-2 pt-4 pb-1 text-[10px] tracking-wider text-muted-foreground/70 uppercase">
      Create
    </div>
    {#each createNav as item}
      <a
        href={item.href}
        class="flex items-center gap-2 rounded-md pl-2 pr-2 py-1.5 text-sm hover:bg-accent
               {isActive(item.href, page.url.pathname) ? 'bg-accent font-medium' : 'text-muted-foreground'}"
      >
        <item.icon class="size-4" />
        {item.label}
      </a>
    {/each}

    <!-- Output group -->
    <div class="px-2 pt-4 pb-1 text-[10px] tracking-wider text-muted-foreground/70 uppercase">
      Output
    </div>
    {#each outputNav as item}
      <a
        href={item.href}
        class="flex items-center gap-2 rounded-md pl-2 pr-2 py-1.5 text-sm hover:bg-accent
               {isActive(item.href, page.url.pathname) ? 'bg-accent font-medium' : 'text-muted-foreground'}"
      >
        <item.icon class="size-4" />
        {item.label}
      </a>
    {/each}

    <!-- Advanced group -->
    <div class="px-2 pt-4 pb-1 text-[10px] tracking-wider text-muted-foreground/70 uppercase">
      Advanced
    </div>
    {#each advancedNav as item}
      <a
        href={item.href}
        class="flex items-center gap-2 rounded-md pl-2 pr-2 py-1.5 text-sm hover:bg-accent
               {isActive(item.href, page.url.pathname) ? 'bg-accent font-medium' : 'text-muted-foreground'}"
      >
        <item.icon class="size-4" />
        {item.label}
      </a>
    {/each}

    <!-- System group -->
    <div class="px-2 pt-4 pb-1 text-[10px] tracking-wider text-muted-foreground/70 uppercase">
      System
    </div>
    {#each systemNav as item}
      <a
        href={item.href}
        class="flex items-center gap-2 rounded-md pl-2 pr-2 py-1.5 text-sm hover:bg-accent
               {isActive(item.href, page.url.pathname) ? 'bg-accent font-medium' : 'text-muted-foreground'}"
      >
        <item.icon class="size-4" />
        {item.label}
      </a>
    {/each}

    <div class="mt-auto">
      <ActivityTray />
    </div>
  </aside>
  <main class="min-h-0 min-w-0 flex-1 overflow-auto">
    {@render children?.()}
  </main>
</div>

<svelte:window onkeydown={onKeydown} />

<!-- Single app-wide palette instance. Studio-only callbacks are read from the
  store (set by the Studio page on mount); off Studio they are undefined and
  the palette falls back to navigation. -->
<CommandPalette
  bind:open={palette.open}
  onfocus={(id) => palette.handlers.onfocus?.(id)}
  onnewstory={() => palette.handlers.onnewstory?.()}
/>

<Toaster richColors />
