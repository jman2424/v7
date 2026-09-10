(() => {
  const config = window.__WIDGET__;
  const input = document.getElementById("chat-input");
  const form = document.getElementById("chat-form");
  const send = document.getElementById("chat-send");
  const log = document.getElementById("chat-log");
  const voice = document.getElementById("voice-status");
  const aloud = document.getElementById("read-aloud");
  const dictation = document.getElementById("dictate");
  const key = "conversation:" + config.tenant;
  let token = "";
  let busy = false;
  try { token = sessionStorage.getItem(key) || ""; } catch {}
  const remember = value => { token = value; try { sessionStorage.setItem(key, value); } catch {} };
  const add = (text, from) => {
    const row = document.createElement("div");
    row.className = from === "me" ? "msg msg--me" : "msg";
    const bubble = document.createElement("div");
    bubble.className = "msg__bubble";
    bubble.textContent = text;
    row.append(bubble); log.append(row); log.scrollTop = log.scrollHeight;
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
          conversation_token: token || undefined, message_id: crypto.randomUUID()})
      });
      const data = await response.json();
      if (!response.ok) {
        if (data.error === "conversation_expired") remember("");
        throw new Error("Request failed");
      }
      remember(data.conversation_token);
      add(data.reply, "bot");
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
