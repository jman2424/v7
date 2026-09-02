/* Web chat widget (no external deps).
   Uses /chat_api; persists sessionId in localStorage per-tenant.
*/

(function () {
  const W = window.__WIDGET__ || {};
  const ENDPOINT = W.endpoint || "/chat_api";
  const TENANT = W.tenant || "EXAMPLE";
  const CHANNEL = W.channel || "web";
  const STORAGE_KEY = `CHAT_SESSION_${TENANT}`;

  // ---------- State ----------
  let sessionId = W.sessionId || localStorage.getItem(STORAGE_KEY) || genId();
  localStorage.setItem(STORAGE_KEY, sessionId);

  // ---------- DOM ----------
  const $ = (sel, root = document) => root.querySelector(sel);
  const log = $("#chat-log");
  const form = $("#chat-form");
  const input = $("#chat-input");
  const btn = $("#chat-send");
  let suggestionRow = null;

  function addMsg(text, from = "bot") {
    const row = document.createElement("div");
    row.className = "msg" + (from === "me" ? " msg--me" : "");
    const bubble = document.createElement("div");
    bubble.className = "msg__bubble";
    bubble.textContent = text;
    const time = document.createElement("span");
    time.className = "msg__time";
    time.textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    row.appendChild(bubble);
    row.appendChild(time);
    log.appendChild(row);
    log.scrollTop = log.scrollHeight;
  }

  function clearSuggestions() {
    if (suggestionRow) {
      suggestionRow.remove();
      suggestionRow = null;
    }
  }

  function addSuggestions(suggestions) {
    clearSuggestions();
    if (!Array.isArray(suggestions) || !suggestions.length) return;

    const row = document.createElement("div");
    row.className = "quick-replies";
    for (const suggestion of suggestions.slice(0, 3)) {
      if (typeof suggestion !== "string" || !suggestion.trim()) continue;
      const choice = document.createElement("button");
      choice.type = "button";
      choice.className = "quick-reply";
      choice.textContent = suggestion;
      choice.addEventListener("click", () => submitText(suggestion));
      row.appendChild(choice);
    }
    if (row.childElementCount) {
      log.appendChild(row);
      suggestionRow = row;
      log.scrollTop = log.scrollHeight;
    }
  }

  function genId() {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return window.crypto.randomUUID();
    }
    return Math.random().toString(36).slice(2) + Date.now().toString(36);
  }

  async function sendMessage(text) {
    btn.disabled = true;
    try {
      const res = await fetch(ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          tenant: TENANT,
          session_id: sessionId,
          client_message_id: genId(),
          metadata: { channel: CHANNEL, widget: "web", embedded: Boolean(W.embedded) }
        })
      });
      if (!res.ok) {
        const t = await res.text().catch(() => "");
        throw new Error(`HTTP ${res.status}: ${t || res.statusText}`);
      }
      const data = await res.json();
      const reply = data.reply || "(no reply)";
      addMsg(reply, "bot");
      addSuggestions(data.agent?.suggested_replies || data.raw?.agent?.suggested_replies);
      // keep session stable if backend sends an id
      if (data.session_id && data.session_id !== sessionId) {
        sessionId = data.session_id;
        localStorage.setItem(STORAGE_KEY, sessionId);
      }
    } catch (e) {
      addMsg("Sorry — I hit a snag. Please try again.", "bot");
      console.error(e);
    } finally {
      btn.disabled = false;
    }
  }

  // ---------- Bindings ----------
  function submitText(text) {
    const message = (text || "").trim();
    if (!message || btn.disabled) return;
    clearSuggestions();
    addMsg(message, "me");
    input.value = "";
    sendMessage(message);
  }

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    submitText(input.value);
  });

  // Greet only once per session (optional)
  if (!sessionStorage.getItem(`greeted_${sessionId}`)) {
    sessionStorage.setItem(`greeted_${sessionId}`, "1");
    // no auto-message to keep it clean; template carries greeting
  }
})();
