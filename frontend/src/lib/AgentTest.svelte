<script lang="ts">
  import { onMount, onDestroy, tick } from 'svelte';

  export let tenant: string;
  export let csrf: string;
  export let apiPrefix = '';
  type Message = { from: 'You' | 'Agent'; text: string };
  type Recognition = {
    lang: string; interimResults: boolean;
    start(): void; abort(): void; stop(): void;
    onstart: (() => void) | null; onend: (() => void) | null;
    onerror: ((event: { error: string }) => void) | null;
    onresult: ((event: { results: { [index: number]: { [index: number]: { transcript: string } } } }) => void) | null;
  };
  let draft = '';
  let messages: Message[] = [];
  const initialQuestions = ['What do you sell?', 'What are your opening hours?', 'What is your delivery policy?'];
  let suggestions = initialQuestions;
  let token = '';
  let busy = false;
  let error = '';
  let voiceStatus = '';
  let readAloud = false;
  let canReadAloud = false;
  let listening = false;
  let recognition: Recognition | undefined;
  let controller: AbortController | undefined;
  let transcript: HTMLDivElement;
  let composer: HTMLTextAreaElement;

  onMount(() => {
    canReadAloud = 'speechSynthesis' in window;
    const speechWindow = window as unknown as { SpeechRecognition?: new () => Recognition; webkitSpeechRecognition?: new () => Recognition };
    const Speech = speechWindow.SpeechRecognition || speechWindow.webkitSpeechRecognition;
    if (!Speech || !window.isSecureContext) {
      voiceStatus = 'Microphone dictation is unavailable in this browser. You can still type your questions.';
      return;
    }
    recognition = new Speech();
    recognition.lang = 'en-GB';
    recognition.interimResults = false;
    recognition.onstart = () => { listening = true; voiceStatus = 'Listening…'; };
    recognition.onresult = event => { draft = (draft + ' ' + event.results[0][0].transcript).trim().slice(0, 4000); };
    recognition.onerror = event => { voiceStatus = event.error === 'not-allowed' ? 'Microphone permission was denied. You can type instead.' : 'Dictation could not finish. Please try again or type.'; };
    recognition.onend = () => { listening = false; if (voiceStatus === 'Listening…') voiceStatus = 'Review the text, then press Send.'; };
  });
  onDestroy(() => {
    controller?.abort();
    recognition?.abort();
    if (canReadAloud) window.speechSynthesis.cancel();
  });

  function dictate() {
    if (listening) { recognition?.stop(); return; }
    if (canReadAloud) window.speechSynthesis.cancel();
    try { recognition?.start(); } catch { voiceStatus = 'Microphone could not start. Try again or type your question.'; }
  }

  function restart() {
    controller?.abort();
    recognition?.abort();
    if (canReadAloud) window.speechSynthesis.cancel();
    token = ''; messages = []; draft = ''; error = ''; busy = false;
    suggestions = initialQuestions;
    composer?.focus();
  }

  async function send() {
    const text = draft.trim();
    if (busy || !text || text.length > 4000) return;
    recognition?.abort();
    if (canReadAloud) window.speechSynthesis.cancel();
    const request = new AbortController();
    controller = request;
    busy = true; error = ''; draft = '';
    messages = [...messages, { from: 'You', text }];
    await tick();
    transcript.scrollTop = transcript.scrollHeight;
    let timedOut = false;
    const timeout = window.setTimeout(() => { timedOut = true; request.abort(); }, 45000);
    try {
      const response = await fetch(apiPrefix + '/admin/api/test-agent?tenant=' + encodeURIComponent(tenant), {
        method: 'POST', credentials: 'same-origin', signal: request.signal,
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
        body: JSON.stringify({ message: text, conversation_token: token || undefined })
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        if (response.status === 401 || data.error === 'csrf_failed') throw new Error('Your session expired. Reload this page and sign in again.');
        if (['test_conversation_expired', 'invalid_test_conversation'].includes(data.error)) { token = ''; throw new Error('This test conversation expired. Start a new conversation and try again.'); }
        if (response.status === 429) throw new Error('Too many requests. Wait a moment, then try again.');
        throw new Error('The agent could not complete this test. Try again or start a new conversation.');
      }
      if (request.signal.aborted) return;
      token = data.conversation_token;
      const reply = String(data.reply || 'No reply was returned.');
      messages = [...messages, { from: 'Agent', text: reply }];
      if (Array.isArray(data.agent?.suggested_replies)) suggestions = data.agent.suggested_replies.filter((item: unknown): item is string => typeof item === 'string').slice(0, 3);
      if (readAloud && canReadAloud) {
        const speech = new SpeechSynthesisUtterance(reply);
        speech.lang = 'en-GB';
        speech.onerror = () => { voiceStatus = 'Audio could not play. The reply is shown in the conversation.'; };
        window.speechSynthesis.speak(speech);
      }
      await tick();
      transcript.scrollTop = transcript.scrollHeight;
    } catch (failure) {
      if (!request.signal.aborted || timedOut) {
        error = timedOut ? 'The test took too long. Try again or start a new conversation.' : failure instanceof Error ? failure.message : 'The test could not complete.';
        draft = text;
      }
    } finally {
      window.clearTimeout(timeout);
      if (controller === request) { busy = false; await tick(); composer?.focus(); }
    }
  }
</script>

<section class="test-card" aria-label="Agent testing">
  <header><div><h2>Try your agent</h2><p>Testing <strong>{tenant}</strong> using its saved business information. These chats do not create sales leads or customer analytics.</p></div><button type="button" on:click={restart}>New conversation</button></header>
  <div class="transcript" bind:this={transcript} role="log" aria-label="Test conversation" aria-live="polite" aria-busy={busy}>
    {#each messages as message}<article class:customer={message.from === 'You'}><strong>{message.from}</strong><p>{message.text}</p></article>
    {:else}<div class="empty"><h3>Ask a question as a customer</h3><p>Try products, prices, opening hours or delivery. Ask follow-up questions to check the agent remembers the conversation.</p></div>{/each}
    {#if busy}<p class="waiting" role="status">The agent is replying…</p>{/if}
  </div>
  <form on:submit|preventDefault={send}>
    {#if suggestions.length}<div class="suggestions" aria-label="Suggested test questions">{#each suggestions as question}<button type="button" disabled={busy} on:click={() => { draft = question; composer.focus(); }}>{question}</button>{/each}</div>{/if}
    <label for="test-message">Your message</label>
    <textarea id="test-message" bind:this={composer} bind:value={draft} maxlength="4000" rows="3" placeholder="Type a question or use the microphone…" required disabled={busy}></textarea>
    <div class="actions"><div class="voice-controls"><button type="button" disabled={!recognition || busy} aria-pressed={listening} on:click={dictate}>{listening ? 'Stop listening' : 'Use microphone'}</button><label class="read-aloud"><input type="checkbox" bind:checked={readAloud} disabled={!canReadAloud} on:change={(event) => { if (!event.currentTarget.checked && canReadAloud) window.speechSynthesis.cancel(); }} />Read replies aloud</label></div><button class="send" type="submit" disabled={busy || !draft.trim()}>{busy ? 'Sending…' : 'Send'}</button></div>
    {#if error}<p class="error" role="alert">{error}</p>{/if}
    {#if voiceStatus}<p class="hint" role="status">{voiceStatus}</p>{/if}
    <p class="hint">Microphone dictation needs your permission and may use your browser’s speech service. Review the text before sending. Save business changes before testing them.</p>
  </form>
</section>

<style>
  .test-card { min-width: 0; border: 1px solid #d9ddd7; border-radius: 8px; background: #fff; overflow-wrap: anywhere; }
  header { display: flex; flex-wrap: wrap; align-items: start; justify-content: space-between; gap: 16px; padding: 20px; border-bottom: 1px solid #e4e8e1; }
  header > div { flex: 1 1 300px; min-width: 0; }
  h2 { margin: 0 0 8px; font-size: 18px; } h3 { margin: 0 0 10px; font-size: 17px; }
  p { margin: 0; line-height: 1.6; } header p, .empty p { color: #67706b; font-size: 14px; }
  button { border: 1px solid #bbc4bc; border-radius: 6px; min-height: 40px; padding: 8px 12px; background: #fff; color: #2f3833; font-size: 14px; font-weight: 600; }
  button:disabled { opacity: .55; cursor: default; } button[aria-pressed='true'] { background: #e7f5ef; border-color: #007d70; }
  button:focus-visible, textarea:focus-visible, input:focus-visible { outline: 3px solid #8bcdc0; outline-offset: 2px; }
  .transcript { height: clamp(260px, 38vh, 460px); overflow-y: auto; padding: 20px; background: #fafbf8; }
  article { max-width: 88%; width: fit-content; margin-bottom: 16px; padding: 14px 16px; background: #fff; border: 1px solid #d9ddd7; border-radius: 8px; font-size: 14px; }
  article strong { display: block; margin-bottom: 6px; font-size: 12px; color: #007d70; } article p { white-space: pre-wrap; }
  article.customer { margin-left: auto; background: #e7f5ef; border-color: #c0dfd3; }
  .empty { max-width: 58ch; margin: 32px auto; text-align: center; } .waiting { color: #67706b; font-size: 14px; }
  form { display: grid; gap: 12px; padding: 20px; border-top: 1px solid #e4e8e1; }
  label { color: #2f3833; font-size: 13px; font-weight: 600; }
  textarea { width: 100%; min-width: 0; resize: vertical; padding: 12px; border: 1px solid #bbc4bc; border-radius: 6px; color: #1f2923; background: #fff; line-height: 1.5; }
  .suggestions, .actions, .voice-controls { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
  .suggestions button { min-height: 34px; font-size: 12px; color: #007d70; background: #f7faf7; }
  .actions { justify-content: space-between; } .read-aloud { display: inline-flex; align-items: center; gap: 7px; }
  .read-aloud input { width: 16px; height: 16px; accent-color: #007d70; }
  .send { padding-inline: 24px; background: #007d70; color: #fff; border-color: #007d70; }
  .hint { color: #67706b; font-size: 12px; } .error { padding: 12px; border-radius: 6px; background: #fff2f0; color: #b42318; font-size: 14px; }
  @media (max-width: 520px) { header, form, .transcript { padding: 16px; } .transcript { height: 200px; } .empty { margin-block: 16px; } article { max-width: 95%; } .send { width: 100%; } }
</style>
