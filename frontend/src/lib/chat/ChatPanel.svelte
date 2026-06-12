<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { get, post } from '$lib/api';
  import ActionCard from '$lib/chat/ActionCard.svelte';
  import { Button } from '$lib/components/ui/button';
  import {
    Conversation,
    ConversationContent
  } from '$lib/components/ai-elements/conversation';
  import { Message, MessageContent } from '$lib/components/ai-elements/message';
  import { Loader } from '$lib/components/ai-elements/loader';
  import {
    Reasoning,
    ReasoningContent,
    ReasoningTrigger
  } from '$lib/components/ai-elements/reasoning';
  import {
    PromptInput,
    PromptInputBody,
    PromptInputSubmit,
    PromptInputTextarea,
    PromptInputToolbar,
    PromptInputTools
  } from '$lib/components/ai-elements/prompt-input';
  import ArrowUpRight from '@lucide/svelte/icons/arrow-up-right';
  import Brain from '@lucide/svelte/icons/brain';
  import ChevronDown from '@lucide/svelte/icons/chevron-down';
  import MessageSquare from '@lucide/svelte/icons/message-square';
  import PenLine from '@lucide/svelte/icons/pen-line';
  import TriangleAlert from '@lucide/svelte/icons/triangle-alert';

  /**
   * Next-step chip: `send` posts the message immediately, `fill` pre-fills the
   * prompt input for the user to finish (e.g. refine instructions), `href`
   * links to a page.
   */
  interface Chip {
    label: string;
    send?: string;
    fill?: string;
    href?: string;
  }

  interface Msg {
    role: 'user' | 'assistant';
    text: string;
    intent?: any;
    options?: any;
    /** Prerequisite warnings from the backend, shown above the action card. */
    warnings?: string[];
    /** Project-state snapshot from the backend (drives the unknown card). */
    state?: any;
    /** Inline next-step suggestions rendered inside the bubble. */
    chips?: Chip[];
  }

  interface SelectedNode {
    id: string;
    kind: string;
    label: string;
  }

  let {
    onfocus,
    onmutate,
    selected = null
  }: {
    onfocus?: (id: string) => void;
    onmutate?: () => void | Promise<void>;
    selected?: SelectedNode | null;
  } = $props();

  let messages = $state<Msg[]>([
    {
      role: 'assistant',
      text: 'Tell me what to do — e.g. 「写一个关于小猫的故事」, "generate a storyboard", or "add captions".'
    }
  ]);
  let input = $state('');
  let busy = $state(false);

  let graphData = $state<any>(null);
  let styleData = $state<any>(null);

  /**
   * One pass over /graph (scenes, shots, storyboards and render jobs are all
   * nodes) shared by the suggestion strip and the post-run follow-ups.
   */
  function analyzeGraph(graph: any) {
    const nodes: any[] = graph?.nodes ?? [];
    const edges: any[] = graph?.edges ?? [];
    const byId = new Map<string, any>(nodes.map((n) => [n.id, n]));

    const characters = nodes.filter((n) => n.type === 'character');
    const scenes = nodes.filter((n) => n.type === 'scene');
    const shots = nodes.filter((n) => n.type === 'shot');
    const outputs = nodes.filter((n) => n.type === 'output');

    const scenesWithShots = new Set(shots.map((sh) => sh.data?.scene_id).filter(Boolean));
    const shotScene = new Map(shots.map((sh) => [sh.id, sh.data?.scene_id]));

    // Storyboard assets are linked to their scene by a metadata edge.
    const scenesWithStoryboard = new Set(
      edges
        .filter((e) => byId.get(e.target)?.data?.asset_type === 'storyboard')
        .map((e) => e.source)
    );

    // A scene counts as rendered when a succeeded render job hangs off it
    // (directly, or via one of its shots).
    const renderedScenes = new Set<string>();
    for (const e of edges) {
      if (byId.get(e.target)?.type !== 'render_job') continue;
      if (byId.get(e.target)?.data?.status !== 'succeeded') continue;
      const sceneId = byId.get(e.source)?.type === 'shot' ? shotScene.get(e.source) : e.source;
      if (sceneId) renderedScenes.add(sceneId);
    }

    /** The next pipeline action for a single scene, if it isn't done yet. */
    function sceneNextChip(sceneId: string, label: string): Chip | null {
      if (!scenesWithShots.has(sceneId))
        return { label: `给《${label}》生成分镜头`, send: `给《${label}》生成分镜头` };
      if (!scenesWithStoryboard.has(sceneId))
        return { label: `给《${label}》生成分镜图`, send: `给《${label}》生成分镜图` };
      if (!renderedScenes.has(sceneId))
        return { label: `Render《${label}》`, send: `render scene 《${label}》` };
      return null;
    }

    return {
      byId,
      characters,
      scenes,
      outputs,
      scenesWithShots,
      scenesWithStoryboard,
      renderedScenes,
      sceneNextChip
    };
  }

  /**
   * Suggest the next steps from the analyzed graph plus /style. When a canvas
   * node is selected, chips target that node instead.
   */
  function computeChips(graph: any, style: any, sel: SelectedNode | null): Chip[] {
    const {
      byId,
      characters,
      scenes,
      outputs,
      scenesWithShots,
      scenesWithStoryboard,
      renderedScenes,
      sceneNextChip
    } = analyzeGraph(graph);

    // Selection-aware chips replace the globals while a node is selected.
    if (sel) {
      const out: Chip[] = [];
      if (sel.kind === 'scene') {
        const next = sceneNextChip(sel.id, sel.label);
        if (next) out.push(next);
        out.push({ label: `改进场景《${sel.label}》…`, fill: `改进场景《${sel.label}》：` });
      } else if (sel.kind === 'shot') {
        out.push({ label: '改进这个镜头…', fill: '改进这个镜头：' });
        const sceneId = byId.get(sel.id)?.data?.scene_id;
        const scene = sceneId ? byId.get(sceneId) : null;
        if (scene) {
          const next = sceneNextChip(scene.id, scene.label);
          if (next) out.push(next);
        }
      } else if (sel.kind === 'output') {
        out.push({ label: '给这个视频加字幕', send: '给这个视频加字幕' });
        const qa = byId.get(sel.id)?.data?.qa_issues;
        if (Array.isArray(qa) && qa.length)
          out.push({ label: 'Fix the latest render', send: 'fix the latest render' });
      } else if (sel.kind === 'character') {
        out.push({
          label: `给《${sel.label}》写一个新故事`,
          send: `给《${sel.label}》写一个新故事`
        });
      }
      if (out.length) return out.slice(0, 3);
      // Unhandled kinds (asset, render_job) fall through to global chips.
    }

    const out: Chip[] = [];
    if (!characters.length) out.push({ label: 'Add characters first', href: '/characters' });
    if (!scenes.length) {
      out.push({ label: '写一个小故事', send: '帮我写一个一个场景的小故事' });
    } else {
      if (!style?.style_prompt) {
        out.push({ label: 'Ingest style from story', send: 'ingest style from story' });
      }
      const noShots = scenes.find((s) => !scenesWithShots.has(s.id));
      if (noShots) out.push({ label: `给《${noShots.label}》生成分镜头`, send: `给《${noShots.label}》生成分镜头` });
      const noStoryboard = scenes.find(
        (s) => scenesWithShots.has(s.id) && !scenesWithStoryboard.has(s.id)
      );
      if (noStoryboard)
        out.push({ label: `给《${noStoryboard.label}》生成分镜图`, send: `给《${noStoryboard.label}》生成分镜图` });
      const notRendered = scenes.find(
        (s) => scenesWithStoryboard.has(s.id) && !renderedScenes.has(s.id)
      );
      if (notRendered)
        out.push({ label: `Render《${notRendered.label}》`, send: `render scene 《${notRendered.label}》` });

      // QA found issues on an output → offer a retry.
      if (outputs.some((o) => Array.isArray(o.data?.qa_issues) && o.data.qa_issues.length)) {
        out.push({ label: 'Fix the latest render', send: 'fix the latest render' });
      }
      // Latest output is missing burned-in captions.
      const latest = outputs[outputs.length - 1];
      if (latest && !latest.data?.captioned_path) {
        out.push({ label: '给最新视频加字幕', send: '给最新视频加字幕' });
      }
      if (scenes.every((s) => renderedScenes.has(s.id))) {
        out.push({ label: '下一个视频：写个新故事', fill: '写一个新故事：' });
        out.push({ label: '建议一些道具', send: '建议一些道具' });
      }
    }
    return out.slice(0, 4);
  }

  let chips = $derived(computeChips(graphData, styleData, selected));

  async function refreshChips() {
    try {
      const [graph, style] = await Promise.all([get('/graph'), get('/style').catch(() => null)]);
      graphData = graph;
      styleData = style;
    } catch {
      graphData = null;
      styleData = null;
    }
  }

  let inputWrapper = $state<HTMLDivElement | null>(null);

  function applyChip(c: Chip) {
    if (c.fill) {
      input = c.fill;
      inputWrapper?.querySelector('textarea')?.focus();
    } else if (c.send) {
      send(c.send);
    }
  }

  onMount(() => {
    refreshChips();
  });

  /** Context passed up by ActionCard after a successful run. */
  interface RunContext {
    action: string;
    sceneId?: string;
    outputId?: string;
  }

  const captionsChip: Chip = { label: '给最新视频加字幕', send: '给最新视频加字幕' };

  /**
   * Compose the assistant follow-up posted after a card runs successfully.
   * Deterministic: derived from the *refreshed* graph, so the chips reflect
   * the state the action just produced. Returns null when there is nothing
   * useful to propose (e.g. unknown actions).
   */
  function buildFollowUp(ctx: RunContext): Msg | null {
    if (!ctx.action || ctx.action === 'unknown') return null;
    const g = analyzeGraph(graphData);

    /** Wrap-up message when a scene's pipeline has nothing left to do. */
    function sceneComplete(title: string): Msg {
      return {
        role: 'assistant',
        text: `《${title}》 is fully rendered.`,
        chips: [captionsChip, { label: '写一个新故事…', fill: '写一个新故事：' }]
      };
    }

    switch (ctx.action) {
      case 'generate_script': {
        const chips = g.scenes
          .map((s) => g.sceneNextChip(s.id, s.label))
          .filter((c): c is Chip => !!c)
          .slice(0, 2);
        return {
          role: 'assistant',
          text: 'Script created. Next: expand a scene.',
          chips
        };
      }
      case 'generate_scenes':
      case 'generate_shots':
      case 'storyboard':
      case 'generate_assets':
      case 'refine_scene':
      case 'refine_shot': {
        if (!ctx.sceneId) return null;
        const title = g.byId.get(ctx.sceneId)?.label ?? 'this scene';
        const next = g.sceneNextChip(ctx.sceneId, title);
        if (!next) return sceneComplete(title);
        return {
          role: 'assistant',
          text: `Done — next for 《${title}》:`,
          chips: [next, { label: `改进场景《${title}》…`, fill: `改进场景《${title}》：` }]
        };
      }
      case 'render_scene':
      case 'render_shot':
      case 'retry_render':
        return {
          role: 'assistant',
          text: 'Render submitted — watch the Activity tray; when it succeeds, captions are one click:',
          chips: [captionsChip]
        };
      case 'caption':
        return {
          role: 'assistant',
          text: 'Captions added.',
          chips: computeChips(graphData, styleData, null).slice(0, 2)
        };
      case 'plan_assets':
        return {
          role: 'assistant',
          text: 'Asset suggestions are on the card above. When you are ready:',
          chips: computeChips(graphData, styleData, null).slice(0, 2)
        };
      case 'style_ingest':
        return {
          role: 'assistant',
          text: 'Style ingested from the story. Next:',
          chips: computeChips(graphData, styleData, null).slice(0, 2)
        };
      case 'delete_scene':
        return {
          role: 'assistant',
          text: 'Scene deleted. Next:',
          chips: computeChips(graphData, styleData, null).slice(0, 2)
        };
      default:
        return null;
    }
  }

  /** Card ran successfully: refresh, then keep the conversation moving. */
  async function handleRan(_result: any, ctx?: RunContext) {
    await onmutate?.();
    await refreshChips();
    if (!ctx) return;
    const follow = buildFollowUp(ctx);
    if (follow) messages.push(follow);
  }

  function intentSummary(intent: any, options: any): string {
    const lines: string[] = [`action: ${intent.action}`];
    if (intent.scene_id) {
      const s = options?.scenes?.find((x: any) => x.id === intent.scene_id);
      lines.push(`scene: ${s?.title ? `${s.title} (${intent.scene_id})` : intent.scene_id}`);
    }
    if (intent.character_id) {
      const c = options?.characters?.find((x: any) => x.id === intent.character_id);
      lines.push(
        `character: ${c?.name ? `${c.name} (${intent.character_id})` : intent.character_id}`
      );
    }
    if (intent.shot_id) lines.push(`shot: ${intent.shot_id}`);
    if (intent.output_id) {
      const o = options?.outputs?.find((x: any) => x.id === intent.output_id);
      const file = o?.video?.split('/').pop();
      lines.push(`output: ${file ? `${file} (${intent.output_id})` : intent.output_id}`);
    }
    if (intent.style) lines.push(`style: ${intent.style}`);
    if (intent.language) lines.push(`language: ${intent.language}`);
    if (intent.idea) lines.push(`idea: ${intent.idea}`);
    if (intent.scene_count != null) lines.push(`scenes: ${intent.scene_count}`);
    if (intent.confidence != null) lines.push(`confidence: ${intent.confidence}`);
    return lines.join('\n\n');
  }

  /** Return keyboard focus to the composer (scoped: card textareas live
   * outside `inputWrapper`, so this can't grab one of them). */
  async function focusComposer() {
    await tick();
    inputWrapper?.querySelector('textarea')?.focus();
  }

  async function send(text?: string) {
    const message = (text ?? input).trim();
    if (!message || busy) return;
    input = '';
    // Conversation memory: the last 6 turns (text only — no cards/state).
    const history = messages.slice(-6).map((m) => ({ role: m.role, text: m.text }));
    messages.push({ role: 'user', text: message });
    busy = true;
    try {
      const r = await post('/chat', { message, history });
      const intent = { ...r.intent };
      // Meta-messages ("我想做一个视频") get echoed back as intent.idea — don't
      // seed the card's Idea field with them; the user should type a real idea.
      if (intent.idea && intent.idea.trim() === message) intent.idea = null;
      messages.push({
        role: 'assistant',
        text: intent.reply,
        intent,
        options: r.options,
        warnings: r.warnings ?? [],
        state: r.state
      });
    } catch (e) {
      messages.push({
        role: 'assistant',
        text: `Something went wrong: ${(e as Error).message}`
      });
    } finally {
      busy = false;
      refreshChips();
      focusComposer(); // the card may have stolen focus — composer stays primary
    }
  }
</script>

{#snippet chipRow(list: Chip[])}
  {#each list as c (c.label)}
    {#if c.href}
      <Button
        variant="secondary"
        size="sm"
        href={c.href}
        class="h-7 shrink-0 rounded-full px-3 text-xs font-normal"
      >
        {c.label}
        <ArrowUpRight class="size-3" />
      </Button>
    {:else}
      <Button
        variant="secondary"
        size="sm"
        class="h-7 shrink-0 rounded-full px-3 text-xs font-normal"
        disabled={busy}
        onclick={() => applyChip(c)}
      >
        {#if c.fill}
          <PenLine class="size-3 text-muted-foreground" />
        {/if}
        {c.label}
      </Button>
    {/if}
  {/each}
{/snippet}

<div class="h-full flex flex-col">
  <div class="flex items-center gap-2 border-b border-border px-4 py-2.5">
    <MessageSquare class="size-4 text-muted-foreground" />
    <span class="text-sm font-semibold">Chat</span>
  </div>

  <Conversation class="flex-1 min-h-0">
    <ConversationContent class="gap-4 overflow-y-auto">
      {#each messages as m, i (i)}
        <Message from={m.role}>
          <MessageContent>
            {#if m.intent}
              <Reasoning class="mb-0" defaultOpen={false}>
                <ReasoningTrigger class="text-xs">
                  <Brain class="size-3.5" />
                  <span>Why this card is pre-filled</span>
                  <ChevronDown class="size-3.5" />
                </ReasoningTrigger>
                <ReasoningContent class="mt-2 text-xs" content={intentSummary(m.intent, m.options)} />
              </Reasoning>
            {/if}
            <p class="whitespace-pre-wrap">{m.text}</p>
            {#if m.chips?.length}
              <div class="mt-2 flex flex-wrap items-center gap-1.5">
                {@render chipRow(m.chips)}
              </div>
            {/if}
            {#if m.warnings?.length}
              <div class="mt-2 space-y-1">
                {#each m.warnings as w (w)}
                  <p class="flex items-start gap-1.5 text-amber-500 text-xs">
                    <TriangleAlert class="size-3.5 shrink-0 mt-0.5" />
                    <span>{w}</span>
                  </p>
                {/each}
              </div>
            {/if}
            {#if m.intent}
              <ActionCard
                intent={m.intent}
                options={m.options}
                projectState={m.state}
                {onfocus}
                onran={handleRan}
                onsuggest={(text) => send(text)}
              />
            {/if}
          </MessageContent>
        </Message>
      {/each}
      {#if busy}
        <Message from="assistant">
          <MessageContent>
            <div class="flex items-center gap-2 text-muted-foreground">
              <Loader size={14} />
              <span class="text-sm">Thinking…</span>
            </div>
          </MessageContent>
        </Message>
      {/if}
    </ConversationContent>
  </Conversation>

  <div class="border-t border-border p-3" bind:this={inputWrapper}>
    {#if chips.length}
      <div class="mb-2 flex flex-wrap items-center gap-1.5 pb-0.5">
        {@render chipRow(chips)}
      </div>
    {/if}
    <PromptInput class="rounded-xl border border-input bg-background shadow-xs" onSubmit={(m) => send(m.text)}>
      <PromptInputBody>
        <PromptInputTextarea
          bind:value={input}
          class="min-h-12 border-0 bg-transparent shadow-none focus-visible:ring-0"
          placeholder="Ask me to generate, render, caption…"
        />
      </PromptInputBody>
      <PromptInputToolbar>
        <PromptInputTools />
        <PromptInputSubmit
          disabled={busy || !input.trim()}
          status={busy ? 'submitted' : 'ready'}
        />
      </PromptInputToolbar>
    </PromptInput>
  </div>
</div>
