(() => {
  const config = window.__WIDGET__;
  const input = document.getElementById("chat-input");
  const form = document.getElementById("chat-form");
  const send = document.getElementById("chat-send");
  const log = document.getElementById("chat-log");
  const voice = document.getElementById("voice-status");
  const aloud = document.getElementById("read-aloud");
  const dictation = document.getElementById("dictate");
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
  const theme = config.theme || {};
  const primary = hex(theme.primary_color) || "#274060";
  const accent = hex(config.accentColor) || hex(theme.accent_color) || primary;
  const background = hex(theme.secondary_color) || "#0e1016";
  const surfaceDirection = luminance(background) > 0.45 ? "#000000" : "#ffffff";
  const panel = mix(background, surfaceDirection, 0.04);
  const field = mix(background, surfaceDirection, 0.08);
  const myBubble = mix(background, accent, 0.16);
  const surfaces = [background, panel, field, myBubble];
  const minimumContrast = colour => Math.min(...surfaces.map(surface => contrast(colour, surface)));
  const preferredText = hex(theme.text_color);
  const automaticText = minimumContrast("#ffffff") >= minimumContrast("#000000") ? "#ffffff" : "#000000";
  const foreground = preferredText && minimumContrast(preferredText) >= 4.5 ? preferredText : automaticText;
  const muted = mix(foreground, background, 0.18);
  const style = document.documentElement.style;
  style.setProperty("--wbg", background);
  style.setProperty("--wpanel", panel);
  style.setProperty("--wfield", field);
  style.setProperty("--wborder", mix(background, surfaceDirection, 0.42));
  style.setProperty("--wtext", foreground);
  style.setProperty("--wmuted", minimumContrast(muted) >= 4.5 ? muted : foreground);
  style.setProperty("--wprimary", primary);
  style.setProperty("--waccent", accent);
  style.setProperty("--waccent-text", readable(accent));
  style.setProperty("--wme", myBubble);
  const font = theme.font_family;
  if (typeof font === "string" && font.length <= 120 && /^[\w\s,.'"\-]+$/.test(font)) {
    style.setProperty("--wfont", font);
  }

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
    if (recognition) recognition.stop();
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
      if (aloud.checked && "speechSynthesis" in window) {
        speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(data.reply);
        utterance.lang = document.documentElement.lang || "en-GB";
        utterance.onerror = () => { voice.textContent = "Audio unavailable. The reply is shown above."; };
        speechSynthesis.speak(utterance);
      }
    } catch {
      add("The message could not be completed. Please try again.", "bot");
      input.value = text;
    } finally {
      clearTimeout(timer); busy = false; send.disabled = false; dictation.disabled = false; input.focus();
    }
  });
  let recognition = null;
  const Speech = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (Speech && window.isSecureContext) {
    recognition = new Speech();
    recognition.lang = document.documentElement.lang || "en-GB";
    recognition.interimResults = false;
    dictation.hidden = false;
    dictation.addEventListener("click", () => {
      if (dictation.getAttribute("aria-pressed") === "true") { recognition.stop(); return; }
      try { recognition.start(); } catch { voice.textContent = "Dictation could not start."; }
    });
    recognition.onstart = () => { dictation.setAttribute("aria-pressed", "true"); dictation.textContent = "Stop"; voice.textContent = "Listening…"; };
    recognition.onresult = event => { input.value = (input.value + " " + event.results[0][0].transcript).trim().slice(0,4000); };
    recognition.onerror = event => { voice.textContent = event.error === "not-allowed" ? "Microphone permission denied. You can type your message." : "Dictation unavailable. Please type your message."; };
    recognition.onend = () => { dictation.setAttribute("aria-pressed", "false"); dictation.textContent = "Dictate"; if (voice.textContent === "Listening…") voice.textContent = "Review your message, then press Send."; };
  } else { voice.textContent = "Dictation is unavailable in this browser. You can type your message."; }
  if (!("speechSynthesis" in window)) { aloud.disabled = true; }
  aloud.addEventListener("change", () => { if (!aloud.checked && "speechSynthesis" in window) speechSynthesis.cancel(); });
  window.addEventListener("pagehide", () => { if (recognition) recognition.stop(); if ("speechSynthesis" in window) speechSynthesis.cancel(); });
})();
