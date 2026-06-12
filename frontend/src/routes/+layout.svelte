<script lang="ts">
  import '../app.css';
  import { page } from '$app/state';
  import { onMount } from 'svelte';
  import { Clapperboard, Image, Users, ListVideo, Film } from '@lucide/svelte';
  import { Toaster } from '$lib/components/ui/sonner';
  import ActivityTray from '$lib/components/ActivityTray.svelte';
  import { initActivity } from '$lib/activity.svelte';

  let { children } = $props();

  onMount(() => initActivity());

  const nav = [
    { href: '/', label: 'Studio', icon: Clapperboard },
    { href: '/assets', label: 'Assets', icon: Image },
    { href: '/characters', label: 'Characters', icon: Users },
    { href: '/scenes', label: 'Scenes', icon: ListVideo },
    { href: '/render', label: 'Render', icon: Film }
  ];

  // The editor is contextual (reached from a render output), so it highlights Render.
  function isActive(href: string, pathname: string): boolean {
    if (href === '/') return pathname === '/';
    if (href === '/render') return pathname.startsWith('/render') || pathname.startsWith('/editor');
    return pathname.startsWith(href);
  }
</script>

<div class="flex h-screen bg-background text-foreground">
  <aside class="flex w-48 shrink-0 flex-col gap-1 border-r border-border p-3">
    <div class="px-2 py-3 text-sm font-semibold tracking-wide">VideoFlow</div>
    {#each nav as item}
      <a
        href={item.href}
        class="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-accent
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
  <main class="flex-1 overflow-auto">
    {@render children?.()}
  </main>
</div>
<Toaster richColors />
