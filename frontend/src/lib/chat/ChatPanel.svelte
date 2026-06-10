<script lang="ts">
  import { post } from '$lib/api';
  import ActionCard from '$lib/chat/ActionCard.svelte';
  import {
    Conversation,
    ConversationContent
  } from '$lib/components/ai-elements/conversation';
  import { Message, MessageContent } from '$lib/components/ai-elements/message';
  import { Button } from '$lib/components/ui/button';
  import { Input } from '$lib/components/ui/input';
  import MessageSquare from '@lucide/svelte/icons/message-square';
  import SendHorizontal from '@lucide/svelte/icons/send-horizontal';

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

  async function send() {
    const message = input.trim();
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
            <p class="whitespace-pre-wrap">{m.text}</p>
            {#if m.intent}
              <ActionCard intent={m.intent} options={m.options} {onfocus} onran={() => onmutate?.()} />
            {/if}
          </MessageContent>
        </Message>
      {/each}
    </ConversationContent>
  </Conversation>

  <form
    class="flex items-center gap-2 border-t border-border p-3"
    onsubmit={(e) => {
      e.preventDefault();
      send();
    }}
  >
    <Input bind:value={input} placeholder="Ask me to generate, render, caption…" disabled={busy} />
    <Button type="submit" size="icon" disabled={busy || !input.trim()} aria-label="Send">
      <SendHorizontal class="size-4" />
    </Button>
  </form>
</div>
