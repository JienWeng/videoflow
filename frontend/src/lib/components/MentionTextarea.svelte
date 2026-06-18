<script lang="ts">
  import { onMount } from 'svelte';
  import { get } from '$lib/api';

  let {
    value = $bindable(''),
    placeholder = '',
    rows = 4,
    id = undefined,
    disabled = false,
    class: className = '',
    oninput = undefined
  }: {
    value?: string;
    placeholder?: string;
    rows?: number;
    id?: string;
    disabled?: boolean;
    class?: string;
    oninput?: (e: Event) => void;
  } = $props();

  type Opt = { name: string; kind: string };
  let el: HTMLTextAreaElement;
  let options = $state<Opt[]>([]);
  let open = $state(false);
  let token = $state('');
  let tokenStart = $state(-1);
  let active = $state(0);

  onMount(loadOptions);

  async function loadOptions() {
    if (cache) {
      options = cache;
      return;
    }
    try {
      const [chars, assets] = await Promise.all([
        get('/characters').catch(() => []),
        get('/assets').catch(() => [])
      ]);
      const opts: Opt[] = [
        ...(chars as any[]).map((c) => ({ name: c.name, kind: 'character' })),
        ...(assets as any[]).map((a) => ({ name: a.name, kind: a.type || 'asset' }))
      ].filter((o) => o.name);
      const seen = new Set<string>();
      cache = opts.filter((o) => (seen.has(o.name) ? false : (seen.add(o.name), true)));
      options = cache;
    } catch {
      /* ignore — picker just won't show */
    }
  }

  const filtered = $derived(
    options.filter((o) => o.name.toLowerCase().includes(token.toLowerCase())).slice(0, 8)
  );

  // Detect an active "@token" immediately before the caret (token = chars after
  // @ up to the next space). Names with spaces are matched by their prefix.
  function detect() {
    const caret = el?.selectionStart ?? value.length;
    const m = value.slice(0, caret).match(/@([^\s@「」]{0,40})$/u);
    if (m) {
      token = m[1];
      tokenStart = caret - m[0].length; // index of '@'
      open = true;
      active = 0;
    } else {
      open = false;
    }
  }

  function onInput(e: Event) {
    detect();
    oninput?.(e);
  }

  function pick(name: string) {
    const caret = el.selectionStart ?? value.length;
    value = value.slice(0, tokenStart) + '@' + name + ' ' + value.slice(caret);
    open = false;
    const pos = tokenStart + name.length + 2; // after "@Name "
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(pos, pos);
      el.dispatchEvent(new Event('input', { bubbles: true }));
    });
  }

  function onKeydown(e: KeyboardEvent) {
    if (!open || !filtered.length) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      active = (active + 1) % filtered.length;
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      active = (active - 1 + filtered.length) % filtered.length;
    } else if (e.key === 'Enter' || e.key === 'Tab') {
      e.preventDefault();
      pick(filtered[active].name);
    } else if (e.key === 'Escape') {
      open = false;
    }
  }
</script>

<script module lang="ts">
  // Shared across instances so we fetch the catalog once.
  let cache: { name: string; kind: string }[] | null = null;
</script>

<div class="relative">
  <textarea
    bind:this={el}
    {id}
    {rows}
    {placeholder}
    {disabled}
    class={className}
    bind:value
    oninput={onInput}
    onkeydown={onKeydown}
    onblur={() => setTimeout(() => (open = false), 150)}
  ></textarea>
  {#if open && filtered.length}
    <ul
      class="absolute z-50 mt-1 max-h-56 w-64 overflow-auto rounded-md border border-border bg-popover p-1 shadow-md"
    >
      {#each filtered as o, i (o.name)}
        <li>
          <button
            type="button"
            class="flex w-full items-center justify-between gap-2 rounded px-2 py-1.5 text-left text-sm {i ===
            active
              ? 'bg-accent'
              : 'hover:bg-accent/60'}"
            onmousedown={(e) => {
              e.preventDefault();
              pick(o.name);
            }}
          >
            <span>@{o.name}</span>
            <span class="text-[10px] text-muted-foreground">{o.kind}</span>
          </button>
        </li>
      {/each}
    </ul>
  {/if}
</div>
