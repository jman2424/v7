<script lang="ts">
  import { onMount, onDestroy, tick } from 'svelte';

  export let tenant: string;
  export let csrf: string;
  export let apiPrefix = '';
  type Message = { id: number; from: 'You' | 'Agent'; text: string };
  type Recognition = {
    lang: string; interimResults: boolean;
    start(): void; abort(): void; stop(): void;
    onstart: (() => void) | null; onend: (() => void) | null;
    onerror: ((event: { error: string }) => void) | null;
    onresult: ((event: { results: { [index: number]: { [index: number]: { transcript: string } } } }) => void) | null;
  };
  let draft = '';
  let messages: Message[] = [];
  const initialQuestions = ['What products or services can you help with?', 'How can I get a quote or make a booking?', 'What are your opening hours?'];
  let suggestions = initialQuestions;
  let token = '';
  let busy = false;
  let error = '';
  let voiceStatus = '';
  let readAloud = false;
  let canReadAloud = false;
  let canDictate = false;
  let listening = false;
  let dictationStarting = false;
  let speechConstructor: (new () => Recognition) | undefined;
  let recognition: Recognition | undefined;
  let dictationTimer: number | undefined;
  let speakingMessageId: number | null = null;
  let speechGeneration = 0;
  let nextMessageId = 0;
  let disposed = false;
  let controller: AbortController | undefined;
  let transcript: HTMLDivElement;
  let composer: HTMLTextAreaElement;

  onMount(() => {
    canReadAloud = 'speechSynthesis' in window && typeof SpeechSynthesisUtterance === 'function';
    const speechWindow = window as unknown as { SpeechRecognition?: new () => Recognition; webkitSpeechRecognition?: new () => Recognition };
    speechConstructor = speechWindow.SpeechRecognition || speechWindow.webkitSpeechRecognition;
    canDictate = Boolean(speechConstructor && window.isSecureContext);
    if (!canDictate) {
      voiceStatus = 'Microphone dictation is unavailable in this browser. You can still type your questions.';
    }
    const cancelVoice = () => { cancelDictation(); stopPlayback(); };
    const onVisibilityChange = () => { if (document.hidden) cancelVoice(); };
    window.addEventListener('pagehide', cancelVoice);
    document.addEventListener('visibilitychange', onVisibilityChange);
    return () => {
      window.removeEventListener('pagehide', cancelVoice);
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  });
  onDestroy(() => {
    disposed = true;
    controller?.abort();
    controller = undefined;
    cancelDictation();
    stopPlayback();
  });

  function cancelDictation() {
    const activeRecognition = recognition;
    recognition = undefined;
    listening = false;
    dictationStarting = false;
    if (['Listening…', 'Starting microphone…', 'Finishing dictation…'].includes(voiceStatus)) voiceStatus = '';
    if (dictationTimer !== undefined) window.clearTimeout(dictationTimer);
    dictationTimer = undefined;
    if (activeRecognition) {
      activeRecognition.onstart = null;
      activeRecognition.onend = null;
      activeRecognition.onerror = null;
      activeRecognition.onresult = null;
      activeRecognition.abort();
    }
  }

  function stopPlayback() {
    speechGeneration++;
    speakingMessageId = null;
    if (canReadAloud) window.speechSynthesis.cancel();
    if (voiceStatus === 'Reading reply aloud…') voiceStatus = '';
  }

  function listenToReply(message: Message) {
    if (!canReadAloud || disposed) return;
    if (speakingMessageId === message.id) { stopPlayback(); voiceStatus = 'Audio stopped.'; return; }
    cancelDictation();
    stopPlayback();
    const generation = speechGeneration;
    const speech = new SpeechSynthesisUtterance(message.text);
    speech.lang = document.documentElement.lang || 'en-GB';
    speakingMessageId = message.id;
    voiceStatus = 'Reading reply aloud…';
    speech.onend = () => {
      if (disposed || generation !== speechGeneration) return;
      speakingMessageId = null;
      if (voiceStatus === 'Reading reply aloud…') voiceStatus = '';
    };
    speech.onerror = event => {
      if (disposed || generation !== speechGeneration) return;
      speakingMessageId = null;
      if (event.error !== 'canceled' && event.error !== 'interrupted') voiceStatus = 'Audio could not play. The reply is shown in the conversation.';
    };
    try { window.speechSynthesis.speak(speech); }
    catch {
      speakingMessageId = null;
      voiceStatus = 'Audio could not play. The reply is shown in the conversation.';
    }
  }

  function finishDictation() {
    window.clearTimeout(dictationTimer);
    dictationTimer = undefined;
    if (!recognition) return;
    voiceStatus = 'Finishing dictation…';
    recognition.stop();
  }

  function dictate() {
    if (listening) { finishDictation(); return; }
    if (!canDictate || !speechConstructor || busy || dictationStarting || disposed) return;
    stopPlayback();
    try {
      const activeRecognition = new speechConstructor();
      recognition = activeRecognition;
      activeRecognition.lang = document.documentElement.lang || 'en-GB';
      activeRecognition.interimResults = false;
      dictationStarting = true;
      voiceStatus = 'Starting microphone…';
      activeRecognition.onstart = () => {
        if (recognition !== activeRecognition || disposed) return;
        listening = true; dictationStarting = false; voiceStatus = 'Listening…';
        dictationTimer = window.setTimeout(finishDictation, 30000);
      };
      activeRecognition.onresult = event => {
        if (recognition !== activeRecognition || busy || disposed) return;
        const text = event.results[0]?.[0]?.transcript;
        if (typeof text === 'string') {
          draft = (draft + ' ' + text).trim().slice(0, 4000);
          voiceStatus = 'Review the text, then press Send.';
        }
      };
      activeRecognition.onerror = event => {
        if (recognition !== activeRecognition || disposed) return;
        const messages: Record<string, string> = {
          'not-allowed': 'Microphone permission was denied. Allow microphone access in your browser settings, or type instead.',
          'service-not-allowed': 'Your browser speech service is unavailable. You can type instead.',
          'audio-capture': 'No microphone was found. Check your device, or type instead.',
          'no-speech': 'No speech was detected. Try again, or type your question.'
        };
        voiceStatus = messages[event.error] || 'Dictation could not finish. Please try again or type.';
      };
      activeRecognition.onend = () => {
        if (recognition !== activeRecognition || disposed) return;
        window.clearTimeout(dictationTimer); dictationTimer = undefined;
        recognition = undefined; listening = false; dictationStarting = false;
        if (['Listening…', 'Starting microphone…', 'Finishing dictation…'].includes(voiceStatus)) voiceStatus = 'Review the text, then press Send.';
      };
      activeRecognition.start();
    } catch {
      cancelDictation();
      voiceStatus = 'Microphone could not start. Try again or type your question.';
    }
  }

  function restart() {
    controller?.abort();
    controller = undefined;
    cancelDictation();
    stopPlayback();
    token = ''; messages = []; draft = ''; error = ''; busy = false;
    if (canDictate) voiceStatus = '';
    suggestions = initialQuestions;
    composer?.focus();
  }

  async function send() {
    const text = draft.trim();
    if (busy || !text || text.length > 4000) return;
    cancelDictation();
    stopPlayback();
    const replySpeechGeneration = speechGeneration;
    const request = new AbortController();
    controller = request;
    busy = true; error = ''; draft = '';
    messages = [...messages, { id: ++nextMessageId, from: 'You', text }];
    await tick();
    if (request.signal.aborted || controller !== request || disposed) return;
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
      if (request.signal.aborted || controller !== request || disposed) return;
      if (!response.ok) {
        if (response.status === 401 || data.error === 'csrf_failed') throw new Error('Your session expired. Reload this page and sign in again.');
        if (['test_conversation_expired', 'invalid_test_conversation'].includes(data.error)) { token = ''; throw new Error('This test conversation expired. Start a new conversation and try again.'); }
        if (response.status === 429) throw new Error('Too many requests. Wait a moment, then try again.');
        throw new Error('The agent could not complete this test. Try again or start a new conversation.');
      }
      token = data.conversation_token;
      const reply = String(data.reply || 'No reply was returned.');
      const message: Message = { id: ++nextMessageId, from: 'Agent', text: reply };
      messages = [...messages, message];
      if (Array.isArray(data.agent?.suggested_replies)) suggestions = data.agent.suggested_replies.filter((item: unknown): item is string => typeof item === 'string').slice(0, 3);
      if (readAloud && canReadAloud && speechGeneration === replySpeechGeneration && !document.hidden) listenToReply(message);
      await tick();
      transcript.scrollTop = transcript.scrollHeight;
    } catch (failure) {
      if (controller === request && !disposed && (!request.signal.aborted || timedOut)) {
        error = timedOut ? 'The test took too long. Try again or start a new conversation.' : failure instanceof Error ? failure.message : 'The test could not complete.';
        draft = text;
      }
    } finally {
      window.clearTimeout(timeout);
      if (controller === request && !disposed) { busy = false; await tick(); composer?.focus(); }
    }
  }
</script>

<section class="test-card" aria-label="Agent testing">
  <header>
    <div><p class="eyebrow">Conversation preview</p><h2>Try your agent</h2><p>Check how <strong>{tenant}</strong> responds using its saved business information.</p></div>
    <button type="button" on:click={restart}>New conversation</button>
  </header>
  <div class="transcript" bind:this={transcript} role="log" aria-label="Test conversation" aria-live="polite" aria-busy={busy}>
    {#each messages as message (message.id)}<article class:customer={message.from === 'You'}><strong>{message.from}</strong><p>{message.text}</p>{#if message.from === 'Agent'}<button class="reply-audio" type="button" disabled={!canReadAloud || busy} aria-label={speakingMessageId === message.id ? 'Stop reading this reply' : 'Read this reply aloud'} aria-pressed={speakingMessageId === message.id} on:click={() => listenToReply(message)}><svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">{#if speakingMessageId === message.id}<rect x="6" y="6" width="12" height="12" rx="1" fill="currentColor" />{:else}<path d="m12 4-5 4H3v8h4l5 4V4Zm4 4a6 6 0 0 1 0 8m3-11a10 10 0 0 1 0 14" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>{/if}</svg>{speakingMessageId === message.id ? 'Stop audio' : 'Listen'}</button>{/if}</article>
    {:else}<div class="empty"><div class="conversation-icon" aria-hidden="true"><svg width="24" height="24" viewBox="0 0 24 24" fill="none"><path d="M20 11.5a7.5 7.5 0 0 1-7.5 7.5H5l-3 3v-9.5A7.5 7.5 0 0 1 9.5 5H13A7 7 0 0 1 20 11.5Z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><path d="M7 10h8M7 14h5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg></div><h3>See the conversation from your customer’s side</h3><p>Ask about an offering, a price or a business policy. Then try a follow-up to check the agent keeps the context.</p></div>{/each}
    {#if busy}<p class="waiting" role="status"><span class="reply-indicator" aria-hidden="true"></span>The agent is replying…</p>{/if}
  </div>
  <form on:submit|preventDefault={send}>
    {#if suggestions.length}<div class="suggestions" aria-label="Suggested test questions">{#each suggestions as question}<button type="button" disabled={busy} on:click={() => { draft = question; composer.focus(); }}>{question}</button>{/each}</div>{/if}
    <label for="test-message">Your message</label>
    <textarea id="test-message" bind:this={composer} bind:value={draft} maxlength="4000" rows="3" placeholder="Type a question or use the microphone…" required disabled={busy}></textarea>
    <div class="actions"><div class="voice-controls"><button class="microphone" type="button" disabled={!canDictate || busy || dictationStarting} aria-label={listening ? 'Stop microphone dictation' : 'Start microphone dictation'} aria-pressed={listening} on:click={dictate}><svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">{#if listening}<rect x="6" y="6" width="12" height="12" rx="1" fill="currentColor" />{:else}<rect x="9" y="2" width="6" height="12" rx="3" stroke="currentColor" stroke-width="1.6"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3m-4 0h8" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>{/if}</svg>{listening ? 'Stop listening' : dictationStarting ? 'Starting…' : 'Use microphone'}</button><label class="read-aloud"><input type="checkbox" bind:checked={readAloud} disabled={!canReadAloud} on:change={(event) => { if (!event.currentTarget.checked) stopPlayback(); }} />Read new replies aloud</label></div><button class="send" type="submit" disabled={busy || !draft.trim()}>{busy ? 'Sending…' : 'Send'}</button></div>
    {#if error}<p class="error" role="alert">{error}</p>{/if}
    {#if voiceStatus}<p class="hint" role="status">{voiceStatus}</p>{/if}
    {#if !canReadAloud}<p class="hint">Read-aloud audio is unavailable in this browser. Replies remain available as text.</p>{/if}
    <div class="test-notes"><p>These test chats do not create sales leads or customer analytics. AI calls still appear in API usage. Save business changes before testing them.</p><p>Microphone dictation needs your permission and may use your browser’s speech service. Dictation stops after 30 seconds. Review the text before sending.</p></div>
  </form>
</section>

<style>
  .test-card { min-width:0; border:1px solid var(--v7-line, #e1e7e4); border-radius:12px; background:var(--v7-surface, #fff); color:var(--v7-ink, #172b26); overflow:hidden; overflow-wrap:anywhere; }
  header { display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:18px; padding:24px; border-bottom:1px solid var(--v7-line, #e1e7e4); }
  header > div { flex:1 1 320px; min-width:0; }
  h2 { margin:0 0 8px; font-size:22px; font-weight:650; letter-spacing:-.025em; }
  h3 { margin:0 0 10px; font-size:18px; font-weight:650; letter-spacing:-.015em; }
  p { margin:0; line-height:1.65; }
  header p, .empty p { color:var(--v7-muted, #64716d); font-size:14px; }
  header .eyebrow { margin:0 0 8px; color:var(--v7-accent, #087f5b); font-size:11px; font-weight:700; letter-spacing:.08em; text-transform:uppercase; }
  button { border:1px solid var(--v7-control-line, #c7d2cc); border-radius:8px; min-height:44px; padding:10px 14px; background:var(--v7-surface, #fff); color:var(--v7-ink, #172b26); font-size:13px; font-weight:600; }
  button:hover:not(:disabled) { background:var(--v7-soft, #edf6f1); border-color:var(--v7-accent, #087f5b); }
  button:disabled { opacity:.55; cursor:default; }
  button[aria-pressed='true'] { background:var(--v7-soft, #edf6f1); border-color:var(--v7-accent, #087f5b); }
  button:focus-visible, textarea:focus-visible, input:focus-visible { outline:3px solid #8bcdc0; outline-offset:3px; }
  .transcript { height:clamp(320px, 42vh, 540px); overflow-y:auto; padding:28px; background:var(--v7-canvas, #f5f7f7); }
  article { max-width:86%; width:fit-content; margin-bottom:18px; padding:16px 18px; background:var(--v7-surface, #fff); border:1px solid var(--v7-line, #e1e7e4); border-radius:12px; border-end-start-radius:4px; font-size:14px; line-height:1.65; }
  article strong { display:block; margin-bottom:7px; font-size:11px; font-weight:700; color:var(--v7-accent, #087f5b); letter-spacing:.025em; }
  article p { white-space:pre-wrap; }
  .reply-audio, .microphone { display:inline-flex; align-items:center; justify-content:center; gap:8px; }
  .reply-audio { margin-top:12px; padding:8px 10px; font-size:12px; background:transparent; }
  article.customer { margin-inline-start:auto; background:var(--v7-soft, #edf6f1); border-color:#d4e7dd; border-end-start-radius:12px; border-end-end-radius:4px; }
  article.customer strong { color:var(--v7-ink, #172b26); }
  .empty { max-width:50ch; margin:22px auto; text-align:center; padding:28px 16px; }
  .conversation-icon { display:grid; place-items:center; width:48px; height:48px; margin:0 auto 18px; border:1px solid #d4e7dd; border-radius:12px; background:var(--v7-soft, #edf6f1); color:var(--v7-accent, #087f5b); }
  .waiting { display:flex; align-items:center; gap:10px; width:fit-content; padding:12px 16px; background:var(--v7-surface, #fff); border:1px solid var(--v7-line, #e1e7e4); border-radius:10px; color:var(--v7-muted, #64716d); font-size:13px; }
  .reply-indicator { width:14px; height:14px; border:2px solid #d4e7dd; border-top-color:var(--v7-accent, #087f5b); border-radius:50%; animation:reply-spin .8s linear infinite; }
  form { display:grid; gap:12px; padding:24px; border-top:1px solid var(--v7-line, #e1e7e4); }
  label { color:var(--v7-ink, #172b26); font-size:13px; font-weight:600; }
  textarea { width:100%; min-width:0; min-height:96px; resize:vertical; padding:12px 14px; border:1px solid var(--v7-control-line, #c7d2cc); border-radius:8px; color:var(--v7-ink, #172b26); background:var(--v7-surface, #fff); line-height:1.6; }
  textarea::placeholder { color:var(--v7-muted, #64716d); }
  .suggestions, .actions, .voice-controls { display:flex; flex-wrap:wrap; gap:10px; align-items:center; }
  .suggestions { margin-bottom:4px; }
  .suggestions button { min-height:40px; padding:8px 12px; font-size:12px; font-weight:500; color:var(--v7-accent, #087f5b); background:var(--v7-soft, #edf6f1); border-color:#d4e7dd; }
  .actions { justify-content:space-between; }
  .voice-controls { gap:12px; }
  .read-aloud { display:inline-flex; align-items:center; gap:8px; min-height:44px; padding:4px 0; font-size:12px; font-weight:500; color:var(--v7-muted, #64716d); cursor:pointer; }
  .read-aloud input { width:17px; height:17px; accent-color:var(--v7-accent, #087f5b); }
  .send { min-width:104px; padding-inline:24px; background:var(--v7-accent, #087f5b); color:#fff; border-color:var(--v7-accent, #087f5b); }
  .send:hover:not(:disabled) { background:var(--v7-brand, #176044); border-color:var(--v7-brand, #176044); }
  .hint, .test-notes { color:var(--v7-muted, #64716d); font-size:12px; }
  .test-notes { display:grid; gap:6px; padding-top:16px; margin-top:4px; border-top:1px solid var(--v7-line, #e1e7e4); }
  .error { padding:12px 14px; border:1px solid #f0cfca; border-radius:8px; background:#fff5f3; color:#a12622; font-size:13px; }
  @keyframes reply-spin { to { transform:rotate(360deg); } }
  @media (prefers-reduced-motion:reduce) { .reply-indicator { animation:none; } }
  @media (max-width:600px) { header, form, .transcript { padding:18px; } header > button { width:100%; } .transcript { height:320px; } .empty { margin-block:10px; padding:18px 8px; } article { max-width:95%; padding:14px; } .send { width:100%; } .voice-controls { width:100%; justify-content:space-between; } .suggestions { gap:8px; } }
</style>
