<script lang="ts">
  import '../app.css';
  import { page } from '$app/stores';

  const links = [
    ['/', 'Dashboard'],
    ['/assets', 'Assets'],
    ['/characters', 'Characters'],
    ['/scenes', 'Scenes'],
    ['/render', 'Render'],
    ['/graph', 'Graph']
  ];
</script>

<div class="layout">
  <nav class="sidebar">
    <div class="brand">🎬 VideoFlow</div>
    {#each links as [href, label]}
      <a {href} class:active={$page.url.pathname === href}>{label}</a>
    {/each}
  </nav>
  <main class="content">
    <slot />
  </main>
</div>
