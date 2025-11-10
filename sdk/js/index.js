/**
 * AI Sales Assistant — Web Widget SDK (iframe bridge)
 *
 * Purpose:
 * - Initialize an iframe pointing to your /chat_ui page.
 * - Maintain a per-tab sessionId.
 * - Provide sendMessage() and onMessage() APIs.
 * - Offer minimal lifecycle: open(), close(), destroy().
 *
 * Contracts:
 * - Server must expose GET /chat_ui and POST /chat_api.
 * - The /chat_ui page must include dashboards/static/js/widget.js
 *   that listens to postMessage events ("ASA_WIDGET:client->iframe")
 *   and responds with ("ASA_WIDGET:iframe->client").
 */

const DEFAULTS = {
  baseUrl: "https://your-app.example.com", // override via init options
  chatUiPath: "/chat_ui",
  container: null, // HTMLElement to mount into; if null, body appended
  tenantKey: null, // optional: business key; appended as ?tenant=KEY
  sessionId: null, // if null, generated
  iframeAttributes: { allow: "clipboard-write; fullscreen" }
};

const EVT_TO_IFRAME = "ASA_WIDGET:client->iframe";
const EVT_FROM_IFRAME = "ASA_WIDGET:iframe->client";

function _uuid() {
  return "asa_" + Math.random().toString(16).slice(2) + Date.now().toString(16);
}

export class AssistantWidget {
  /**
   * @param {Object} opts - { baseUrl, chatUiPath, container, tenantKey, sessionId, iframeAttributes }
   */
  constructor(opts = {}) {
    this.opts = { ...DEFAULTS, ...opts };
    this.baseUrl = this.opts.baseUrl.replace(/\/+$/, "");
    this.chatUiPath = this.opts.chatUiPath || DEFAULTS.chatUiPath;
    this.tenantKey = this.opts.tenantKey || null;
    this.sessionId = this.opts.sessionId || _uuid();

    /** @type {HTMLIFrameElement|null} */
    this.iframe = null;
    /** @type {HTMLElement} */
    this.container = this.opts.container || document.body;

    /** @type {Map<string, Function[]>} */
    this.handlers = new Map();

    this._boundOnMessage = this._onMessage.bind(this);
    window.addEventListener("message", this._boundOnMessage, false);
  }

  _buildUrl() {
    const u = new URL(this.chatUiPath, this.baseUrl);
    u.searchParams.set("session", this.sessionId);
    if (this.tenantKey) u.searchParams.set("tenant", this.tenantKey);
    return u.toString();
  }

  open() {
    if (this.iframe) return this.iframe;

    const iframe = document.createElement("iframe");
    iframe.src = this._buildUrl();
    iframe.style.border = "0";
    iframe.style.width = "100%";
    iframe.style.height = "100%";
    for (const [k, v] of Object.entries(this.opts.iframeAttributes || {})) {
      iframe.setAttribute(k, v);
    }

    // If container is body, create a default floating panel
    if (this.container === document.body) {
      const wrapper = document.createElement("div");
      wrapper.style.position = "fixed";
      wrapper.style.bottom = "20px";
      wrapper.style.right = "20px";
      wrapper.style.width = "380px";
      wrapper.style.height = "520px";
      wrapper.style.zIndex = "2147483646";
      wrapper.style.boxShadow = "0 8px 24px rgba(0,0,0,0.18)";
      wrapper.style.borderRadius = "12px";
      wrapper.style.overflow = "hidden";
      wrapper.style.background = "#fff";
      wrapper.appendChild(iframe);
      this.container.appendChild(wrapper);
      this.wrapper = wrapper;
    } else {
      this.container.appendChild(iframe);
      this.wrapper = null;
    }

    this.iframe = iframe;
    // Notify iframe we exist (handshake)
    this._post({ type: "hello", sessionId: this.sessionId, tenantKey: this.tenantKey });
    return this.iframe;
  }

  close() {
    if (!this.iframe) return;
    if (this.wrapper && this.wrapper.parentNode) {
      this.wrapper.parentNode.removeChild(this.wrapper);
    } else if (this.iframe.parentNode) {
      this.iframe.parentNode.removeChild(this.iframe);
    }
    this.iframe = null;
    this.wrapper = null;
  }

  destroy() {
    this.close();
    window.removeEventListener("message", this._boundOnMessage, false);
    this.handlers.clear();
  }

  setSession(sessionId) {
    this.sessionId = sessionId || _uuid();
    if (this.iframe) {
      // Update iframe about new session
      this._post({ type: "session:update", sessionId: this.sessionId });
    }
  }

  sendMessage(text, metadata = {}) {
    if (!text || typeof text !== "string") return;
    this._post({ type: "chat:message", sessionId: this.sessionId, text, metadata });
  }

  on(eventType, handler) {
    if (!this.handlers.has(eventType)) this.handlers.set(eventType, []);
    this.handlers.get(eventType).push(handler);
    return () => {
      const arr = this.handlers.get(eventType) || [];
      const i = arr.indexOf(handler);
      if (i >= 0) arr.splice(i, 1);
    };
  }

  _emit(eventType, payload) {
    const arr = this.handlers.get(eventType) || [];
    for (const fn of arr) {
      try { fn(payload); } catch (e) { /* ignore */ }
    }
  }

  _post(payload) {
    if (!this.iframe || !this.iframe.contentWindow) return;
    this.iframe.contentWindow.postMessage({ __asa: EVT_TO_IFRAME, payload }, "*");
  }

  _onMessage(ev) {
    const msg = ev?.data;
    if (!msg || msg.__asa !== EVT_FROM_IFRAME) return;

    const { type, data } = msg.payload || {};
    switch (type) {
      case "ready":
        this._emit("ready", data);
        break;
      case "chat:reply":
        // data: { reply, raw }
        this._emit("message", data);
        break;
      case "chat:typing":
        this._emit("typing", data);
        break;
      case "error":
        this._emit("error", data);
        break;
      case "metrics":
        this._emit("metrics", data); // latency, deflection flag, etc.
        break;
      default:
        this._emit("event", msg.payload);
    }
  }
}

/**
 * Convenience helper
 */
export function initAssistantWidget(options = {}) {
  const w = new AssistantWidget(options);
  w.open();
  return w;
}
