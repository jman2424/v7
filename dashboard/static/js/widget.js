(() => {
  const config = window.__WIDGET__;
  const input = document.getElementById("chat-input");
  const form = document.getElementById("chat-form");
  const send = document.getElementById("chat-send");
  const log = document.getElementById("chat-log");
  const voice = document.getElementById("voice-status");
  const aloud = document.getElementById("read-aloud");
  const dictation = document.getElementById("dictate");
  const dictationLabel = document.getElementById("dictate-label");
  const stopAudio = document.getElementById("stop-speaking");
  const closeChat = document.getElementById("chat-close");
  const actionSection = document.getElementById("chat-actions");
  const actionButtons = document.getElementById("chat-action-buttons");
  const actionStatus = document.getElementById("chat-action-status");
  const actionRetry = document.getElementById("chat-action-retry");
  const actionForm = document.getElementById("chat-action-form");
  const actionTitle = document.getElementById("chat-action-title");
  const actionSlotRow = document.getElementById("chat-action-slot-row");
  const actionSlot = document.getElementById("chat-action-slot");
  const actionSlotNote = document.getElementById("chat-action-slot-note");
  const actionName = document.getElementById("chat-action-name");
  const actionContact = document.getElementById("chat-action-contact");
  const actionContactLabel = document.getElementById("chat-action-contact-label");
  const actionDetails = document.getElementById("chat-action-details");
  const actionConsent = document.getElementById("chat-action-consent");
  const actionSubmit = document.getElementById("chat-action-submit");
  const actionCancel = document.getElementById("chat-action-cancel");

  const actionLabels = {
    consultation: "Book a consultation",
    quote: "Request a quote",
    callback: "Ask for a callback"
  };
  const actionTitles = {
    consultation: "Consultation request",
    quote: "Quote request",
    callback: "Callback request"
  };
  const key = "conversation:" + config.tenant;
  let token = "";
  let actionToken = "";
  let busy = false;
  let actionBusy = false;
  let activeAction = "";
  let actionRequestId = "";
  let availableActions = {};
  try { token = sessionStorage.getItem(key) || ""; } catch {}
  const remember = value => {
    token = typeof value === "string" ? value : "";
    try { sessionStorage.setItem(key, token); } catch {}
  };

  // Tenant theme values are data: accept only colours and a plain font stack.
  const hex = value => {
    if (typeof value !== "string" || !/^#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?$/.test(value)) return null;
    return value.length === 4
      ? "#" + [...value.slice(1)].map(char => char + char).join("")
      : value;
  };
  const rgb = colour => [1, 3, 5].map(index => parseInt(colour.slice(index, index + 2), 16));
  const mix = (first, second, amount) => {
    const a = rgb(first), b = rgb(second);
    return "#" + a.map((value, index) => Math.round(value * (1 - amount) + b[index] * amount)
      .toString(16).padStart(2, "0")).join("");
  };
  const luminance = colour => rgb(colour).map(value => {
    const channel = value / 255;
    return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
  }).reduce((sum, value, index) => sum + value * [0.2126, 0.7152, 0.0722][index], 0);
  const contrast = (first, second) => {
    const a = luminance(first), b = luminance(second);
    return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
  };
  const readable = background => contrast(background, "#ffffff") >= contrast(background, "#000000") ? "#ffffff" : "#000000";
  const presets = {
    midnight: {background: "#0e1016", panel: "#131826", field: "#191e2a", text: "#eaf0ff", bubble: "#0b1c12"},
    daylight: {background: "#f3f6fa", panel: "#ffffff", field: "#f7f9fc", text: "#182338", bubble: "#e8f3ee"},
    minimal: {background: "#ffffff", panel: "#ffffff", field: "#f7f9f7", text: "#202422", bubble: "#f1f6f2"},
    editorial: {background: "#f5f0e6", panel: "#fffaf0", field: "#fffdf7", text: "#2b281f", bubble: "#eee8d8"},
    neon: {background: "#080c16", panel: "#101729", field: "#0d1628", text: "#eff8ff", bubble: "#142a32"},
    warm: {background: "#f7eee6", panel: "#fff8f1", field: "#fffaf5", text: "#3e2d2b", bubble: "#f4e3d9"},
    glass: {background: "#19365d", panel: "#243f63", field: "#2c496f", text: "#ffffff", bubble: "#35577a"},
    studio: {background: "#f4f5f7", panel: "#ffffff", field: "#f7f8fa", text: "#202933", bubble: "#e8edf4"},
    soft: {background: "#eef5f1", panel: "#fbfdfb", field: "#f1f7f2", text: "#233d30", bubble: "#dcefe3"},
    bold: {background: "#f4f5f5", panel: "#ffffff", field: "#eef1f0", text: "#142b23", bubble: "#e4f4eb"}
  };
  const preset = presets[document.body.dataset.style] || presets.midnight;
  const theme = config.theme || {};
  const colours = config.colors || {};
  const primary = hex(theme.primary_color) || "#274060";
  const accent = hex(config.accentColor) || hex(theme.accent_color) || primary;
  const customBackground = hex(colours.background) || (document.body.dataset.style === "midnight" ? hex(theme.secondary_color) : null);
  const background = customBackground || preset.background;
  const surfaceDirection = luminance(background) > 0.45 ? "#000000" : "#ffffff";
  const customPanel = hex(colours.surface);
  const panel = customPanel || (customBackground ? mix(background, surfaceDirection, 0.04) : preset.panel);
  const field = customPanel || customBackground ? mix(panel, readable(panel), 0.04) : preset.field;
  const myBubble = hex(colours.bubble) || (customBackground ? mix(background, accent, 0.16) : preset.bubble);
  const preferredText = hex(colours.text) || (document.body.dataset.style === "midnight" ? hex(theme.text_color) : null) || preset.text;
  const textOn = surface => contrast(preferredText, surface) >= 4.5 ? preferredText : readable(surface);
  const foreground = textOn(background);
  const panelText = textOn(panel);
  const muted = mix(foreground, background, 0.18);
  // Body-scoped properties override preset palettes while keeping their shapes.
  const style = document.body.style;
  style.setProperty("--wbg", background);
  style.setProperty("--wpanel", panel);
  style.setProperty("--wfield", field);
  style.setProperty("--wborder", mix(panel, readable(panel), 0.5));
  style.setProperty("--wtext", foreground);
  style.setProperty("--wpanel-text", panelText);
  style.setProperty("--wfield-text", textOn(field));
  style.setProperty("--wme-text", textOn(myBubble));
  style.setProperty("--wmuted", contrast(muted, background) >= 4.5 ? muted : foreground);
  const panelMuted = mix(panelText, panel, 0.18);
  style.setProperty("--wpanel-muted", contrast(panelMuted, panel) >= 4.5 ? panelMuted : panelText);
  style.setProperty("--wprimary", primary);
  style.setProperty("--waccent", accent);
  style.setProperty("--waccent-text", readable(accent));
  style.setProperty("--wme", myBubble);
  const font = theme.font_family;
  if (typeof font === "string" && font.length <= 120 && /^[\w\s,.'"\-]+$/.test(font)) {
    style.setProperty("--wfont", font);
  }

  const speechAvailable = "speechSynthesis" in window && typeof window.SpeechSynthesisUtterance === "function";
  let speakingButton = null;
  let speechGeneration = 0;
  const resetAudio = () => {
    if (speakingButton) { speakingButton.textContent = "Listen"; speakingButton.setAttribute("aria-label", "Read this reply aloud"); speakingButton.setAttribute("aria-pressed", "false"); }
    speakingButton = null;
    stopAudio.hidden = true;
  };
  const cancelAudio = () => {
    speechGeneration++;
    if (speechAvailable) window.speechSynthesis.cancel();
    resetAudio();
  };
  const speak = (text, button) => {
    if (!speechAvailable) return;
    if (button === speakingButton) { cancelAudio(); voice.textContent = "Audio stopped."; return; }
    cancelAudio();
    const generation = speechGeneration;
    const utterance = new window.SpeechSynthesisUtterance(text);
    utterance.lang = document.documentElement.lang || "en-GB";
    speakingButton = button;
    button.textContent = "Stop audio";
    button.setAttribute("aria-label", "Stop reading this reply");
    button.setAttribute("aria-pressed", "true");
    stopAudio.hidden = false;
    utterance.onend = () => { if (generation === speechGeneration) { resetAudio(); voice.textContent = "Audio finished."; } };
    utterance.onerror = () => { if (generation === speechGeneration) { resetAudio(); voice.textContent = "Audio unavailable. Use Listen to try again; the reply remains above."; } };
    try { window.speechSynthesis.speak(utterance); }
    catch { resetAudio(); voice.textContent = "Audio unavailable. The reply remains above."; }
  };
  const addPlayback = (bubble, text) => {
    if (!speechAvailable) return null;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "widget__listen";
    button.textContent = "Listen";
    button.setAttribute("aria-label", "Read this reply aloud");
    button.setAttribute("aria-pressed", "false");
    button.addEventListener("click", () => {
      if (dictation.getAttribute("aria-pressed") === "true") { voice.textContent = "Stop the microphone before playing audio."; return; }
      speak(text, button);
    });
    bubble.append(button);
    return button;
  };

  const newRequestId = () => {
    if (window.crypto && typeof crypto.randomUUID === "function") return crypto.randomUUID();
    if (window.crypto && typeof crypto.getRandomValues === "function") {
      const bytes = new Uint8Array(16);
      crypto.getRandomValues(bytes);
      return [...bytes].map(byte => byte.toString(16).padStart(2, "0")).join("");
    }
    return String(Date.now()) + String(Math.random());
  };
  const add = (text, from) => {
    const row = document.createElement("div");
    row.className = from === "me" ? "msg msg--me" : "msg";
    const bubble = document.createElement("div");
    bubble.className = "msg__bubble";
    const content = document.createElement("span");
    content.textContent = text;
    bubble.append(content);
    row.append(bubble); log.append(row); log.scrollTop = log.scrollHeight;
    return bubble;
  };
  const setActionStatus = (message, isError = false) => {
    actionStatus.textContent = message;
    actionStatus.classList.toggle("widget__action-status--error", isError);
  };
  const actionEnabled = action => availableActions[action] && availableActions[action].enabled === true;
  const makeActionButton = action => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "widget__action-button";
    const slots = availableActions.consultation && availableActions.consultation.slots;
    button.textContent = action === "consultation" && (!Array.isArray(slots) || !slots.length)
      ? "Request a consultation" : actionLabels[action];
    button.addEventListener("click", () => openAction(action));
    return button;
  };
  const renderActionButtons = () => {
    actionButtons.replaceChildren();
    Object.keys(actionLabels).filter(actionEnabled).forEach(action => actionButtons.append(makeActionButton(action)));
    if (activeAction && !actionEnabled(activeAction)) {
      activeAction = "";
      actionForm.hidden = true;
    }
    actionSection.hidden = !actionButtons.childElementCount;
  };
  const refreshSlots = selected => {
    actionSlot.replaceChildren();
    const slots = activeAction === "consultation" && Array.isArray(availableActions.consultation.slots)
      ? availableActions.consultation.slots.filter(slot => slot && typeof slot.id === "string" && typeof slot.label === "string")
      : [];
    actionSlotRow.hidden = !slots.length;
    actionSlotNote.hidden = activeAction !== "consultation" || !!slots.length;
    actionSlot.required = !!slots.length;
    if (slots.length) {
      actionSlot.add(new Option("Choose a time", ""));
      slots.forEach(slot => {
        const date = new Date(slot.start_at);
        const localTime = Number.isNaN(date.getTime()) ? "" : date.toLocaleString(undefined, {
          year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short"
        });
        actionSlot.add(new Option(localTime ? slot.label + " — " + localTime : slot.label, slot.id));
      });
      if (slots.some(slot => slot.id === selected)) actionSlot.value = selected;
    }
  };
  const loadActions = async () => {
    actionRetry.hidden = true;
    const url = new URL(config.actionsEndpoint, window.location.origin);
    url.searchParams.set("tenant", config.tenant);
    try {
      const response = await fetch(url, {credentials: "same-origin"});
      if (!response.ok) throw new Error("Action options unavailable");
      const data = await response.json();
      availableActions = data && typeof data === "object" ? data : {};
      actionToken = typeof availableActions.conversation_token === "string" ? availableActions.conversation_token : "";
      if (!actionToken) throw new Error("Missing request token");
      renderActionButtons();
      if (activeAction === "consultation") refreshSlots(actionSlot.value);
      setActionStatus("");
    } catch {
      availableActions = {};
      actionButtons.replaceChildren();
      actionForm.hidden = true;
      actionSection.hidden = false;
      actionRetry.hidden = false;
      setActionStatus("Booking and request options could not be loaded. You can still use chat.", true);
    }
  };
  const openAction = action => {
    if (!actionEnabled(action) || actionBusy) return;
    activeAction = action;
    actionRequestId = newRequestId();
    actionForm.reset();
    actionTitle.textContent = actionTitles[action];
    actionContactLabel.textContent = action === "callback" ? "Phone number" : "Email or phone";
    actionContact.autocomplete = action === "callback" ? "tel" : "email";
    actionContact.inputMode = action === "callback" ? "tel" : "text";
    refreshSlots("");
    actionForm.hidden = false;
    setActionStatus("");
    actionName.focus();
  };
  const closeAction = () => {
    if (actionBusy) return;
    activeAction = "";
    actionRequestId = "";
    actionForm.hidden = true;
    setActionStatus("");
    const first = actionButtons.querySelector("button");
    if (first) first.focus();
  };
  actionForm.addEventListener("input", () => {
    if (actionStatus.classList.contains("widget__action-status--error")) setActionStatus("");
  });
  actionForm.addEventListener("submit", async event => {
    event.preventDefault();
    if (!activeAction || actionBusy || !actionEnabled(activeAction)) return;
    if (!actionForm.reportValidity()) return;
    if (!actionName.value.trim()) { setActionStatus("Enter your name.", true); actionName.focus(); return; }
    if (!actionContact.value.trim()) { setActionStatus("Enter your contact details.", true); actionContact.focus(); return; }
    actionBusy = true;
    actionSubmit.disabled = true;
    actionCancel.disabled = true;
    setActionStatus("Sending your request…");
    const action = activeAction;
    const payload = {
      tenant: config.tenant,
      action,
      name: actionName.value.trim(),
      contact: actionContact.value.trim(),
      details: actionDetails.value.trim(),
      consent: actionConsent.checked,
      conversation_token: actionToken || token || undefined,
      idempotency_key: actionRequestId
    };
    if (action === "consultation" && actionSlot.value) payload.slot_id = actionSlot.value;
    const selectedTime = action === "consultation" && actionSlot.value
      ? actionSlot.options[actionSlot.selectedIndex].textContent : "";
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 30000);
    try {
      const response = await fetch(config.actionsEndpoint, {
        method: "POST", credentials: "same-origin",
        headers: {"Content-Type": "application/json"},
        signal: controller.signal,
        body: JSON.stringify(payload)
      });
      const data = await response.json();
      if (!response.ok || !data || data.ok !== true) {
        const error = data && typeof data.error === "string" ? data.error : "";
        if (error === "slot_unavailable") {
          actionRetry.hidden = false;
          throw new Error("That time is no longer available. Reload the options and choose another time.");
        }
        if (error === "rate_limited") throw new Error("Too many requests. Please wait a few minutes before trying again.");
        if (error === "invalid_contact") throw new Error(action === "callback"
          ? "Enter a valid phone number for a callback."
          : "Enter a valid email address or phone number.");
        if (error === "idempotency_conflict") throw new Error("This request changed during a retry. It may already have been received. Restore the original details before retrying.");
        if (error === "action_unavailable") {
          actionRetry.hidden = false;
          throw new Error("This option is no longer available. Reload the options and choose another way to continue.");
        }
        if (error === "invalid_conversation" || error === "conversation_expired") {
          remember("");
          actionRetry.hidden = false;
          throw new Error("This request session expired. Reload the options, then send again.");
        }
        throw new Error("Your request could not be sent. Please try again.");
      }
      const reference = typeof data.reference === "string" && data.reference ? " Reference: " + data.reference + "." : "";
      const confirmed = action === "consultation" && data.status === "confirmed";
      setActionStatus(confirmed
        ? "Your consultation is confirmed for " + selectedTime + "." + reference
        : "Your " + (action === "callback" ? "callback" : action === "quote" ? "quote" : "consultation") + " request was received. The business can follow up using your contact details." + reference);
      actionForm.hidden = true;
      activeAction = "";
      actionRequestId = "";
    } catch (error) {
      const message = error && error.name === "AbortError"
        ? "The connection timed out. Retry without changing the form; the same request reference will be reused if it was received."
        : error instanceof Error ? error.message : "Your request could not be sent. Please try again.";
      setActionStatus(message, true);
    } finally {
      clearTimeout(timer);
      actionBusy = false;
      actionSubmit.disabled = false;
      actionCancel.disabled = false;
    }
  });
  actionCancel.addEventListener("click", closeAction);
  actionRetry.addEventListener("click", loadActions);
  loadActions();

  const addSuggestedActions = (bubble, suggestions) => {
    if (!Array.isArray(suggestions)) return;
    const names = [...new Set(suggestions.map(item => typeof item === "string" ? item : item && (item.action || item.type)))]
      .filter(action => Object.prototype.hasOwnProperty.call(actionLabels, action) && actionEnabled(action));
    if (!names.length) return;
    const group = document.createElement("div");
    group.className = "msg__actions";
    group.setAttribute("role", "group");
    group.setAttribute("aria-label", "Suggested next steps");
    names.forEach(action => group.append(makeActionButton(action)));
    bubble.append(group);
  };
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const text = input.value.trim();
    if (busy || !text) return;
    busy = true; send.disabled = true; dictation.disabled = true;
    cancelAudio();
    const replySpeechGeneration = speechGeneration;
    acceptingRecognition = false;
    if (recognition) recognition.abort();
    recordingRequestId++;
    if (transcriptionController) transcriptionController.abort();
    transcriptionController = null;
    transcribing = false;
    recordingStarting = false;
    stopRecording(true);
    releaseMicrophone();
    microphoneState(false);
    add(text, "me"); input.value = "";
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 45000);
    try {
      const response = await fetch(config.endpoint, {
        method: "POST", headers: {"Content-Type": "application/json"},
        signal: controller.signal,
        body: JSON.stringify({tenant: config.tenant, message: text,
          conversation_token: token || undefined, message_id: newRequestId()})
      });
      const data = await response.json();
      if (!response.ok) {
        if (data.error === "conversation_expired") remember("");
        throw new Error("Request failed");
      }
      remember(data.conversation_token);
      const bubble = add(data.reply, "bot");
      addSuggestedActions(bubble, data.actions);
      const playback = addPlayback(bubble, data.reply);
      if (aloud.checked && playback && replySpeechGeneration === speechGeneration && !document.hidden) speak(data.reply, playback);
    } catch {
      add("The message could not be completed. Please try again.", "bot");
      input.value = text;
    } finally {
      clearTimeout(timer); busy = false; send.disabled = false; dictation.disabled = transcribing; input.focus();
    }
  });
  let recognition = null;
  let acceptingRecognition = false;
  let recognitionStarting = false;
  let recognitionTimer = null;
  let recorder = null;
  let mediaStream = null;
  let recordingTimer = null;
  let discardRecording = false;
  let transcribing = false;
  let recordingRequestId = 0;
  let recordingStarting = false;
  let transcriptionController = null;
  const microphoneState = (active, label = "Microphone") => {
    dictation.setAttribute("aria-pressed", String(active));
    dictation.setAttribute("aria-label", active ? "Stop microphone dictation" : "Start microphone dictation");
    dictationLabel.textContent = label;
  };
  const stopRecording = discard => {
    if (!recorder || recorder.state !== "recording") return;
    discardRecording = !!discard;
    dictation.disabled = true;
    recorder.stop();
  };
  const releaseMicrophone = (stream = mediaStream) => {
    if (stream === mediaStream) {
      if (recordingTimer) clearTimeout(recordingTimer);
      recordingTimer = null;
      mediaStream = null;
    }
    if (stream) stream.getTracks().forEach(track => track.stop());
  };
  const Speech = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (Speech && window.isSecureContext) {
    recognition = new Speech();
    recognition.lang = document.documentElement.lang || "en-GB";
    recognition.interimResults = false;
    dictation.hidden = false;
    dictation.addEventListener("click", () => {
      if (dictation.getAttribute("aria-pressed") === "true") { recognition.stop(); return; }
      if (busy || recognitionStarting) return;
      cancelAudio();
      acceptingRecognition = true;
      recognitionStarting = true;
      dictation.disabled = true;
      try { recognition.start(); }
      catch { acceptingRecognition = false; recognitionStarting = false; dictation.disabled = busy; voice.textContent = "Microphone could not start. Try again or type your message."; }
    });
    recognition.onstart = () => {
      recognitionStarting = false;
      if (!acceptingRecognition || busy) { recognition.abort(); return; }
      dictation.disabled = false;
      microphoneState(true, "Stop");
      voice.textContent = "Listening… Press Stop when finished (30 seconds maximum).";
      recognitionTimer = setTimeout(() => recognition.stop(), 30000);
    };
    recognition.onresult = event => {
      if (!acceptingRecognition || busy) return;
      const transcript = event.results[0] && event.results[0][0] && event.results[0][0].transcript;
      if (typeof transcript === "string") input.value = (input.value + " " + transcript).trim().slice(0, 4000);
    };
    recognition.onerror = event => {
      acceptingRecognition = false;
      voice.textContent = ["not-allowed", "service-not-allowed"].includes(event.error)
        ? "Microphone permission denied. Allow microphone access in your browser or type your message."
        : event.error === "no-speech" ? "No speech was detected. Try again or type your message."
        : event.error === "aborted" ? "Microphone stopped. You can type your message."
        : "Dictation unavailable. Please type your message.";
    };
    recognition.onend = () => {
      if (recognitionTimer) clearTimeout(recognitionTimer);
      recognitionTimer = null;
      acceptingRecognition = false;
      recognitionStarting = false;
      microphoneState(false);
      dictation.disabled = busy;
      if (voice.textContent.startsWith("Listening…")) voice.textContent = "Review your message, then press Send.";
    };
  } else if (window.isSecureContext && config.transcriptionEnabled && window.MediaRecorder && navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
    dictation.hidden = false;
    dictation.addEventListener("click", async () => {
      if (recorder && recorder.state === "recording") { stopRecording(false); return; }
      if (busy || transcribing) return;
      cancelAudio();
      dictation.disabled = true;
      recordingStarting = true;
      const requestId = ++recordingRequestId;
      let acquiredStream = null;
      try {
        acquiredStream = await navigator.mediaDevices.getUserMedia({audio: true});
        if (busy || requestId !== recordingRequestId) { acquiredStream.getTracks().forEach(track => track.stop()); return; }
        recordingStarting = false;
        mediaStream = acquiredStream;
        const options = ["audio/webm;codecs=opus", "audio/mp4", "audio/webm"]
          .find(type => MediaRecorder.isTypeSupported(type));
        recorder = new MediaRecorder(mediaStream, options ? {mimeType: options} : undefined);
        const activeRecorder = recorder;
        const chunks = [];
        discardRecording = false;
        recorder.ondataavailable = event => { if (event.data && event.data.size) chunks.push(event.data); };
        let activeTimer = null;
        recorder.onerror = () => {
          if (requestId !== recordingRequestId) return;
          voice.textContent = "Recording failed. You can type your message.";
          stopRecording(true);
        };
        recorder.onstop = async () => {
          if (activeTimer) clearTimeout(activeTimer);
          releaseMicrophone(acquiredStream);
          if (requestId !== recordingRequestId) return;
          microphoneState(false);
          if (discardRecording) { dictation.disabled = busy; return; }
          const mimeType = activeRecorder.mimeType || (chunks[0] && chunks[0].type) || "";
          const audio = new Blob(chunks, {type: mimeType});
          if (!audio.size) { voice.textContent = "No audio was recorded. Please try again."; dictation.disabled = busy; return; }
          if (audio.size > 4 * 1024 * 1024) { voice.textContent = "Recording is too large. Try a shorter message."; dictation.disabled = busy; return; }
          transcribing = true;
          dictation.disabled = true;
          voice.textContent = "Turning speech into text…";
          const payload = new FormData();
          payload.append("audio", audio, mimeType.startsWith("audio/mp4") ? "message.m4a" : "message.webm");
          const controller = new AbortController();
          transcriptionController = controller;
          const timer = setTimeout(() => controller.abort(), 35000);
          try {
            const response = await fetch(config.transcriptionEndpoint, {
              method: "POST", credentials: "same-origin", body: payload,
              headers: {"X-V7-Transcription-Token": config.transcriptionToken},
              signal: controller.signal
            });
            const result = await response.json();
            if (!response.ok || !result || typeof result.text !== "string") {
              if (result && result.error === "rate_limited") throw new Error("Please wait before recording another message.");
              if (result && result.error === "no_speech_detected") throw new Error("No speech was detected. Please try again.");
              if (result && result.error === "invalid_transcription_token") throw new Error("Reload the chat to use Dictate again.");
              throw new Error("Voice transcription is unavailable. You can type your message.");
            }
            if (requestId !== recordingRequestId) return;
            input.value = (input.value + " " + result.text).trim().slice(0, 4000);
            voice.textContent = "Review your message, then press Send.";
            input.focus();
          } catch (error) {
            if (requestId !== recordingRequestId) return;
            voice.textContent = error && error.name === "AbortError"
              ? "Transcription timed out. Please try again or type your message."
              : error instanceof Error ? error.message : "Voice transcription is unavailable. You can type your message.";
          } finally {
            clearTimeout(timer);
            if (transcriptionController === controller) {
              transcriptionController = null;
              transcribing = false;
              dictation.disabled = busy || recordingStarting;
            }
          }
        };
        recorder.start();
        dictation.disabled = false;
        microphoneState(true, "Stop");
        voice.textContent = "Recording… Press Stop when finished (30 seconds maximum).";
        activeTimer = setTimeout(() => { if (activeRecorder.state === "recording") activeRecorder.stop(); }, 30000);
        recordingTimer = activeTimer;
      } catch {
        if (requestId !== recordingRequestId) { if (acquiredStream) acquiredStream.getTracks().forEach(track => track.stop()); return; }
        recordingStarting = false;
        releaseMicrophone(acquiredStream);
        dictation.disabled = busy;
        voice.textContent = "Microphone unavailable. You can type your message.";
      }
    });
  } else { voice.textContent = "Microphone dictation is unavailable in this browser. You can type your message."; }
  if (!speechAvailable) { aloud.disabled = true; aloud.parentElement.title = "Audio playback is unavailable in this browser."; }
  aloud.addEventListener("change", () => { if (!aloud.checked) cancelAudio(); });
  stopAudio.addEventListener("click", () => { cancelAudio(); voice.textContent = "Audio stopped."; });
  const releaseVoice = () => {
    acceptingRecognition = false;
    recognitionStarting = false;
    if (recognitionTimer) clearTimeout(recognitionTimer);
    recognitionTimer = null;
    if (recognition) recognition.abort();
    recordingRequestId++;
    if (transcriptionController) transcriptionController.abort();
    transcriptionController = null;
    transcribing = false;
    recordingStarting = false;
    stopRecording(true);
    releaseMicrophone();
    microphoneState(false);
    dictation.disabled = busy;
    cancelAudio();
  };
  if (closeChat) closeChat.addEventListener("click", () => {
    releaseVoice();
    // The embed loader checks both the source window and widget origin.
    const parentOrigin = document.referrer ? new URL(document.referrer).origin : "*";
    window.parent.postMessage({type: "V7_WIDGET_CLOSE"}, parentOrigin);
  });
  window.addEventListener("message", event => {
    if (!closeChat || window.parent === window || event.source !== window.parent || !event.data || event.data.type !== "V7_WIDGET_HIDE") return;
    const approvedOrigins = Array.isArray(config.parentOrigins) ? config.parentOrigins : [];
    if (event.origin !== window.location.origin && !approvedOrigins.includes(event.origin)) return;
    releaseVoice();
  });
  window.addEventListener("pagehide", releaseVoice);
  document.addEventListener("visibilitychange", () => { if (document.hidden) releaseVoice(); });
})();
