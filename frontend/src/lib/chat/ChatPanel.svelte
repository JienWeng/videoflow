<script lang="ts">
  import { post } from '$lib/api';
  import ActionCard from '$lib/chat/ActionCard.svelte';
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
  import Brain from '@lucide/svelte/icons/brain';
  import ChevronDown from '@lucide/svelte/icons/chevron-down';
  import MessageSquare from '@lucide/svelte/icons/message-square';

  interface Msg {
    role: 'user' | 'assistant';
    text: string;
    intent?: any;
    options?: any;
  }

  let {
    onfocus,
    onmutate
  }: { onfocus?: (id: string) => void; onmutate?: () => void | Promise<void> } = $props();

  let messages = $state<Msg[]>([
    {
      role: 'assistant',
      text: 'Tell me what to do — e.g. 「给乐乐的场景生成分镜图」, "render scene 我是乐乐", or "add captions".'
    }
  ]);
  let input = $state('');
  let busy = $state(false);

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

  async function send(text?: string) {
    const message = (text ?? input).trim();
    if (!message || busy) return;
    input = '';
    messages.push({ role: 'user', text: message });
    busy = true;
    try {
      const r = await post('/chat', { message });
      messages.push({
        role: 'assistant',
        text: r.intent.reply,
        intent: r.intent,
        options: r.options
      });
    } catch (e) {
      messages.push({
        role: 'assistant',
        text: `Something went wrong: ${(e as Error).message}`
      });
    } finally {
      busy = false;
    }
  }
</script>

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
            {#if m.intent}
              <ActionCard
                intent={m.intent}
                options={m.options}
                {onfocus}
                onran={() => onmutate?.()}
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

  <div class="border-t border-border p-3">
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
