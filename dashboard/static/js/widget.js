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

  function genId() {
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
          session_id: sessionId,
          metadata: { channel: CHANNEL, widget: "web" }
        })
      });
      if (!res.ok) {
        const t = await res.text().catch(() => "");
        throw new Error(`HTTP ${res.status}: ${t || res.statusText}`);
      }
      const data = await res.json();
      const reply = data.reply || "(no reply)";
      addMsg(reply, "bot");
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
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = (input.value || "").trim();
    if (!text) return;
    addMsg(text, "me");
    input.value = "";
    sendMessage(text);
  });

  // Greet only once per session (optional)
  if (!sessionStorage.getItem(`greeted_${sessionId}`)) {
    sessionStorage.setItem(`greeted_${sessionId}`, "1");
    // no auto-message to keep it clean; template carries greeting
  }
})();
