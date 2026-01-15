/* static/js/admin.js
   Admin controller: KPIs + Leads + CSV export + Self-repair + Editor modal
*/
(function () {
  const S = window.__ADMIN__ || {};
  const CSRF = S.csrfToken || "";
  const TENANT = (S.tenant || "").trim(); // IMPORTANT

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  // ---- URL helper: always include tenant ----
  function withTenant(path) {
    try {
      // supports relative paths like "/admin/api/kpis?minutes=1440"
      const u = new URL(path, window.location.origin);
      if (TENANT && !u.searchParams.get("tenant")) {
        u.searchParams.set("tenant", TENANT);
      }
      return u.toString();
    } catch (_) {
      // last resort
      if (!TENANT) return path;
      return path.includes("?")
        ? `${path}&tenant=${encodeURIComponent(TENANT)}`
        : `${path}?tenant=${encodeURIComponent(TENANT)}`;
    }
  }

  // ---------- Toast ----------
  function toast(msg, type = "ok") {
    const tpl = $("#toast-template");
    if (!tpl) {
      console.log(`[${type}]`, msg);
      return;
    }
    const node = tpl.content.firstElementChild.cloneNode(true);
    node.querySelector(".toast__msg").textContent = msg;

    if (type === "error") {
      node.style.background = "#2a1b1b";
      node.style.borderColor = "#4d2828";
      node.style.color = "#fca5a5";
    } else if (type === "warn") {
      node.style.background = "#281f0f";
      node.style.borderColor = "#5f4313";
      node.style.color = "#fde68a";
    }

    document.body.appendChild(node);
    node.querySelector(".toast__close")?.addEventListener("click", () => node.remove());
    setTimeout(() => node.remove(), 4500);
  }

  // ---------- HTTP helpers ----------
  async function apiJSON(path, opts = {}) {
    const headers = Object.assign(
      { "Content-Type": "application/json" },
      CSRF ? { "X-CSRF-Token": CSRF } : {},
      opts.headers || {}
    );

    const res = await fetch(withTenant(path), Object.assign({}, opts, {
      headers,
      credentials: "include",
      cache: "no-store",
    }));

    const ct = res.headers.get("content-type") || "";
    if (!res.ok) {
      const txt = await res.text().catch(() => "");
      throw new Error(`HTTP ${res.status}: ${txt || res.statusText}`);
    }
    if (ct.includes("application/json")) return res.json();
    // If backend accidentally returns text, still show it
    return { ok: true, raw: await res.text().catch(() => "") };
  }

  function minutesFromSelect() {
    const v = $("#period-select")?.value || "1440";
    const n = parseInt(v, 10);
    return Number.isFinite(n) ? n : 1440;
  }

  function escapeHtml(s) {
    return (s || "").toString()
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  // ---------- KPIs ----------
  async function loadKPIs() {
    const out = $("#kpi-output");
    if (out && !out.textContent.trim()) out.textContent = "Waiting for data…";

    const minutes = minutesFromSelect();
    const kpis = await apiJSON(`/admin/api/kpis?minutes=${minutes}`);

    if (out) out.textContent = JSON.stringify(kpis, null, 2);

    // Optional labels
    try {
      const mode = await apiJSON("/mode");
      if ($("#mode-label")) $("#mode-label").textContent = mode.mode || "?";
    } catch (_) {}

    try {
      const ver = await apiJSON("/version");
      if ($("#version-label")) $("#version-label").textContent = ver.version || "?";
    } catch (_) {}

    return kpis;
  }

  // ---------- Leads ----------
  async function loadLeads() {
    const tbody = $("#leads-table tbody");
    if (!tbody) return;

    tbody.innerHTML = `<tr><td colspan="6">Loading…</td></tr>`;

    const data = await apiJSON(`/admin/api/leads?limit=50`);
    const items = data.items || [];

    tbody.innerHTML = "";

    if (!items.length) {
      tbody.innerHTML = `<tr><td colspan="6">No leads yet.</td></tr>`;
      return;
    }

    for (const l of items) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${escapeHtml(l.updated_utc || "")}</td>
        <td>${escapeHtml(l.name || "")}</td>
        <td>${escapeHtml(l.phone || "")}</td>
        <td>${escapeHtml(l.status || "")}</td>
        <td>${escapeHtml(l.tags || "")}</td>
        <td>${escapeHtml(l.last_session_id || "")}</td>
      `;
      tbody.appendChild(tr);
    }
  }

  // ---------- CSV export ----------
  function exportLeadsCSV() {
    // include tenant
    window.location.href = withTenant(`/admin/api/leads.csv`);
  }

  // ---------- Self-repair (optional) ----------
  async function runSelfRepair() {
    const out = $("#validation-output");
    if (out) out.textContent = "Running…";

    try {
      const rep = await apiJSON("/__diag/self_repair");
      if (out) out.textContent = JSON.stringify(rep, null, 2);
      toast("Self-repair report updated");
    } catch (e) {
      if (out) out.textContent = `Self-repair not available: ${e.message}`;
      toast("Self-repair endpoint missing", "warn");
    }
  }

  // ---------- Editor modal (optional) ----------
  const modal = $("#editor-modal");
  const editorForm = $("#editor-form");
  const editorJson = $("#editor-json");
  const editorOutput = $("#editor-output");
  const tabs = modal ? $$(".tab", modal) : [];

  function openEditor(kind) {
    if (!modal) return toast("Editor UI missing", "warn");
    modal.hidden = false;
    setActiveTab(kind);
    loadEditor(kind).catch(e => {
      if (editorOutput) editorOutput.textContent = e.message;
      toast(e.message, "error");
    });
  }

  function closeEditor() {
    if (!modal) return;
    modal.hidden = true;
    if (editorJson) editorJson.value = "";
    if (editorOutput) editorOutput.textContent = "Awaiting input…";
  }

  function setActiveTab(kind) {
    if (!modal || !editorForm) return;
    tabs.forEach(t => t.classList.toggle("is-active", t.dataset.tab === kind));
    editorForm.dataset.kind = kind;
    const title = $("#editor-title");
    if (title) title.textContent = `Edit ${kind.toUpperCase()}`;
  }

  async function loadEditor(kind) {
    if (!editorJson || !editorOutput) return;
    editorJson.value = "Loading…";
    editorOutput.textContent = "";

    const path = kind === "catalog" ? "/admin/api/catalog" : "/admin/api/faq";
    const data = await apiJSON(path);
    editorJson.value = JSON.stringify(data, null, 2);
    editorOutput.textContent = "Loaded.";
  }

  async function validateEditor() {
    if (!editorJson || !editorOutput || !editorForm) return;

    const kind = editorForm.dataset.kind;
    const data = JSON.parse(editorJson.value);

    const res = await apiJSON(`/admin/api/validate/${kind}`, {
      method: "POST",
      body: JSON.stringify({ data }),
    });

    editorOutput.textContent = JSON.stringify(res, null, 2);
    toast("Validation passed");
  }

  async function saveEditor(ev) {
    ev.preventDefault();
    if (!editorJson || !editorOutput || !editorForm) return;

    const kind = editorForm.dataset.kind;
    const data = JSON.parse(editorJson.value);

    const res = await apiJSON(`/admin/api/${kind}`, {
      method: "PUT",
      body: JSON.stringify(data),
    });

    editorOutput.textContent = JSON.stringify(res, null, 2);
    toast(`${kind.toUpperCase()} saved`);
  }

  // ---------- Bind ----------
  function bind() {
    $("#refresh-kpis")?.addEventListener("click", () => {
      Promise.all([loadKPIs(), window.DashChartsReload?.()]).catch(e => toast(e.message, "error"));
    });

    $("#period-select")?.addEventListener("change", () => {
      Promise.all([loadKPIs(), window.DashChartsReload?.()]).catch(e => toast(e.message, "error"));
    });

    $("#export-leads")?.addEventListener("click", exportLeadsCSV);

    // Editor
    $$(".btn[data-editor-target]").forEach(btn => {
      btn.addEventListener("click", () => openEditor(btn.dataset.editorTarget));
    });
    $("#editor-close")?.addEventListener("click", closeEditor);
    $("#editor-validate")?.addEventListener("click", () => validateEditor().catch(e => toast(e.message, "error")));
    $("#editor-save")?.addEventListener("click", (e) => saveEditor(e).catch(err => toast(err.message, "error")));

    // Self-repair
    $("#run-self-repair")?.addEventListener("click", () => runSelfRepair().catch(e => toast(e.message, "error")));

    // Optional mode toggle endpoint
    $("#toggle-mode-v5")?.addEventListener("click", () => setMode("V5"));
    $("#toggle-mode-v6")?.addEventListener("click", () => setMode("AIV6"));
    $("#toggle-mode-v7")?.addEventListener("click", () => setMode("AIV7"));
  }

  async function setMode(mode) {
    try {
      await apiJSON("/admin/api/mode", { method: "POST", body: JSON.stringify({ mode }) });
      if ($("#mode-label")) $("#mode-label").textContent = mode;
      toast(`Mode switched to ${mode}`);
    } catch (e) {
      toast(e.message, "error");
    }
  }

  // ---------- Init ----------
  window.addEventListener("DOMContentLoaded", () => {
    bind();

    // show what tenant the UI believes it is on
    if (TENANT) toast(`Tenant: ${TENANT}`, "warn");

    Promise.all([
      loadKPIs(),
      loadLeads(),
      runSelfRepair(),
      window.DashChartsReload?.(),
    ]).catch(e => toast(e.message, "error"));
  });
})();
