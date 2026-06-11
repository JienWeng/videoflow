<script lang="ts">
  import { PaneGroup, Pane, Handle } from '$lib/components/ui/resizable';
  import EntityCanvas from '$lib/canvas/EntityCanvas.svelte';
  import NodePanel from '$lib/canvas/NodePanel.svelte';
  import ChatPanel from '$lib/chat/ChatPanel.svelte';
  import * as Card from '$lib/components/ui/card';
  import { get } from '$lib/api';
  import { subscribeJobs } from '$lib/sse';
  import { onMount } from 'svelte';
  import type { Node } from '@xyflow/svelte';
  import Users from '@lucide/svelte/icons/users';
  import Palette from '@lucide/svelte/icons/palette';
  import MessageSquare from '@lucide/svelte/icons/message-square';
  import ArrowUpRight from '@lucide/svelte/icons/arrow-up-right';

  let canvas: EntityCanvas | undefined = $state();
  let selected = $state<Node | null>(null);
  // -1 = unknown (don't flash the empty state before the first /graph response).
  let nodeCount = $state(-1);

  async function checkEmpty() {
    try {
      const g = await get('/graph');
      nodeCount = g.nodes?.length ?? 0;
    } catch {
      // leave nodeCount as-is; no overlay on errors
    }
  }

  function refreshAll() {
    canvas?.refresh();
    checkEmpty();
  }

  onMount(() => {
    checkEmpty();
    return subscribeJobs(refreshAll, refreshAll);
  });
</script>

<PaneGroup direction="horizontal" class="h-full">
  <Pane defaultSize={72} minSize={40}>
    <div class="relative h-full">
      <EntityCanvas bind:this={canvas} onselect={(n) => (selected = n)} />
      {#if nodeCount === 0}
        <div class="pointer-events-none absolute inset-0 z-10 grid place-items-center">
          <Card.Root class="pointer-events-auto max-w-sm shadow-lg">
            <Card.Header>
              <Card.Title>Start your project</Card.Title>
              <Card.Description>
                Three steps and your first video is on its way.
              </Card.Description>
            </Card.Header>
            <Card.Content>
              <ol class="space-y-3 text-sm">
                <li class="flex items-start gap-2.5">
                  <Users class="size-4 mt-0.5 shrink-0 text-muted-foreground" />
                  <span>
                    <a href="/characters" class="font-medium underline underline-offset-2 inline-flex items-center gap-0.5">
                      Add characters<ArrowUpRight class="size-3" />
                    </a>
                    <span class="block text-muted-foreground">
                      Upload photos so they look the same in every video.
                    </span>
                  </span>
                </li>
                <li class="flex items-start gap-2.5">
                  <Palette class="size-4 mt-0.5 shrink-0 text-muted-foreground" />
                  <span>
                    <a href="/assets" class="font-medium underline underline-offset-2 inline-flex items-center gap-0.5">
                      Set the style<ArrowUpRight class="size-3" />
                    </a>
                    <span class="block text-muted-foreground">
                      A project style guide is applied to everything generated.
                    </span>
                  </span>
                </li>
                <li class="flex items-start gap-2.5">
                  <MessageSquare class="size-4 mt-0.5 shrink-0 text-muted-foreground" />
                  <span>
                    <span class="font-medium">Write a script</span>
                    <span class="block text-muted-foreground">
                      Tell the chat on the right what your story is about.
                    </span>
                  </span>
                </li>
              </ol>
            </Card.Content>
          </Card.Root>
        </div>
      {/if}
    </div>
  </Pane>
  <Handle withHandle />
  <Pane defaultSize={28} minSize={20}>
    <div class="h-full border-l border-border">
      <ChatPanel
        onfocus={(id) => canvas?.focusNode(id)}
        onmutate={refreshAll}
        selected={selected
          ? {
              id: selected.id,
              kind: String(selected.data?.kind ?? ''),
              label: String(selected.data?.label ?? '')
            }
          : null}
      />
    </div>
  </Pane>
</PaneGroup>

<NodePanel node={selected} onclose={() => (selected = null)} onsaved={() => canvas?.refresh()} />
