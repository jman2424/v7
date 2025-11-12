/* Admin dashboard controller.
   Wires charts, CRUD, self-repair, uploads, mode toggles, and toasts.
*/

(function () {
  const S = window.__ADMIN__ || {};
  const CSRF = S.csrfToken;

  // ---------- Utilities ----------
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  function toast(msg, type = "ok") {
    let tpl = $("#toast-template");
    if (!tpl) { console.log("[toast]", msg); return; }
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
    const close = node.querySelector(".toast__close");
    close.onclick = () => node.remove();
    setTimeout(() => node.remove(), 4500);
  }

  async function api(path, opts = {}) {
    const headers = Object.assign({
      "Content-Type": "application/json",
      "X-CSRF-Token": CSRF
    }, opts.headers || {});
    const res = await fetch(path, Object.assign({}, opts, { headers }));
    if (!res.ok) {
      const txt = await res.text().catch(() => "");
      throw new Error(`HTTP ${res.status}: ${txt || res.statusText}`);
    }
    const ct = res.headers.get("content-type") || "";
    return ct.includes("application/json") ? res.json() : res.text();
  }

  function qsParams(obj) {
    const p = new URLSearchParams();
    Object.entries(obj).forEach(([k, v]) => {
      if (v !== undefined && v !== null) p.set(k, v);
    });
    return p.toString();
  }

  // ---------- Charts ----------
  let chartVolume, chartIntents, chartItems;

  async function loadKpis() {
    const period = $("#period-select").value || "1440";
    const query = `?${qsParams({ period: period + "m" })}`; // backend may accept minutes or period string
    const summary = await api(`/analytics/summary${query}`);
    const series = await api(`/analytics/timeseries${query}`).catch(() => ({ series: [] }));

    // Volume timeseries
    const elVol = $("#chart-volume");
    if (!chartVolume) chartVolume = window.DashCharts.line(elVol, series.series || []);
    else chartVolume.update(series.series || []);

    // Top intents bar
    const elInt = $("#chart-intents");
    const intents = (summary.top_intents || []).map(r => ({ key: r.key, count: r.count }));
    if (!chartIntents) chartIntents = window.DashCharts.bar(elInt, intents);
    else chartIntents.update(intents);

    // Top items bar
    const elItems = $("#chart-items");
    const items = (summary.top_items || []).map(r => ({ key: r.key, count: r.count }));
    if (!chartItems) chartItems = window.DashCharts.bar(elItems, items);
    else chartItems.update(items);

    // Mode + version labels
    $("#mode-label").textContent = (await api("/mode").catch(() => ({ mode: "?" }))).mode || "?";
    $("#version-label").textContent = (await api("/version").catch(() => ({ version: "?" }))).version || "?";
  }

  // ---------- Leads ----------
  async function loadLeads() {
    const rows = await api("/admin/api/leads").catch(() => []);
    const tbody = $("#leads-table tbody");
    tbody.innerHTML = "";
    rows.forEach(l => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${escapeHtml(l.updated_at || "")}</td>
        <td>${escapeHtml(l.name || "")}</td>
        <td>${escapeHtml(l.phone || "")}</td>
        <td>${escapeHtml(l.status || "")}</td>
        <td>${(l.tags || []).map(escapeHtml).join(", ")}</td>
        <td>${escapeHtml(l.session_id || "")}</td>
      `;
      tbody.appendChild(tr);
    });
  }

  function escapeHtml(s) {
    return (s || "").toString()
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  // ---------- Validation / Self-repair ----------
  async function runSelfRepair() {
    $("#validation-output").textContent = "Running…";
    const rep = await api("/__diag/self_repair").catch(e => ({ status: "error", message: e.message }));
    $("#validation-output").textContent = JSON.stringify(rep, null, 2);
    toast("Self-repair report updated");
  }

  // ---------- Editors ----------
  const modal = $("#editor-modal");
  const editorForm = $("#editor-form");
  const editorJson = $("#editor-json");
  const editorOutput = $("#editor-output");
  const tabs = $$(".tab", modal);

  function openEditor(kind) {
    modal.hidden = false;
    setActiveTab(kind);
    loadEditor(kind);
  }

  function closeEditor() {
    modal.hidden = true;
    editorJson.value = "";
    editorOutput.textContent = "Awaiting input…";
  }

  function setActiveTab(kind) {
    tabs.forEach(t => t.classList.toggle("is-active", t.dataset.tab === kind));
    editorForm.dataset.kind = kind;
    $("#editor-title").textContent = `Edit ${kind.toUpperCase()}`;
  }

  async function loadEditor(kind) {
    editorJson.value = "Loading…";
    const path = kind === "catalog" ? "/admin/api/catalog" : "/admin/api/faq";
    const data = await api(path);
    editorJson.value = JSON.stringify(data, null, 2);
    editorOutput.textContent = "Loaded.";
  }

  async function validateEditor() {
    try {
      const data = JSON.parse(editorJson.value);
      const kind = editorForm.dataset.kind;
      const res = await api(`/admin/api/validate/${kind}`, { method: "POST", body: JSON.stringify({ data }) });
      editorOutput.textContent = JSON.stringify(res, null, 2);
      toast("Validation passed");
    } catch (e) {
      editorOutput.textContent = `Validation error: ${e.message}`;
      toast("Validation failed", "error");
    }
  }

  async function saveEditor(ev) {
    ev.preventDefault();
    try {
      const data = JSON.parse(editorJson.value);
      const kind = editorForm.dataset.kind;
      const res = await api(`/admin/api/${kind}`, { method: "PUT", body: JSON.stringify(data) });
      editorOutput.textContent = JSON.stringify(res, null, 2);
      toast(`${kind.toUpperCase()} saved`);
    } catch (e) {
      editorOutput.textContent = `Save error: ${e.message}`;
      toast("Save failed", "error");
    }
  }

  // ---------- Uploads / Snapshot ----------
  async function uploadJson(file) {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("csrf_token", CSRF);
    const res = await fetch("/files/upload", { method: "POST", body: fd });
    if (!res.ok) throw new Error(`Upload failed: ${res.status}`);
    toast("Upload complete");
  }

  async function downloadSnapshot() {
    const res = await fetch("/files/snapshot?tenant=" + encodeURIComponent(S.tenant), {
      headers: { "X-CSRF-Token": CSRF }
    });
    if (!res.ok) return toast("Snapshot download failed", "error");
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${S.tenant}-snapshot.tar.gz`;
    a.click();
    toast("Snapshot downloaded");
  }

  // ---------- Mode toggles ----------
  async function setMode(mode) {
    try {
      await api("/admin/api/mode", { method: "POST", body: JSON.stringify({ mode }) });
      $("#mode-label").textContent = mode;
      toast(`Mode switched to ${mode}`);
    } catch (e) {
      toast(e.message, "error");
    }
  }

  // ---------- Tenant switch ----------
  function switchTenant(k) {
    const url = new URL(window.location.href);
    url.searchParams.set("tenant", k);
    window.location.href = url.toString();
  }

  // ---------- Bindings ----------
  function bind() {
    $("#refresh-kpis").addEventListener("click", () => loadKpis().catch(e => toast(e.message, "error")));
    $("#period-select").addEventListener("change", () => loadKpis().catch(e => toast(e.message, "error")));
    $("#export-leads").addEventListener("click", async () => {
      const res = await fetch("/analytics/export", { headers: { "X-CSRF-Token": CSRF } });
      if (!res.ok) return toast("Export failed", "error");
      const blob = await res.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "analytics.csv";
      a.click();
    });

    // Editor modal
    $$(".btn[data-editor-target]").forEach(btn => {
      btn.addEventListener("click", () => openEditor(btn.dataset.editorTarget));
    });
    $("#editor-close").addEventListener("click", closeEditor);
    $$(".tab", modal).forEach(t => t.addEventListener("click", () => setActiveTab(t.dataset.tab)));
    $("#editor-validate").addEventListener("click", () => validateEditor().catch(e => toast(e.message, "error")));
    $("#editor-save").addEventListener("click", saveEditor);
    $("#upload-json").addEventListener("click", () => $("#json-file").click());
    $("#json-file").addEventListener("change", async (e) => {
      const f = e.target.files[0];
      if (!f) return;
      try { await uploadJson(f); } catch (err) { toast(err.message, "error"); }
      finally { e.target.value = ""; }
    });
    $("#download-snapshot").addEventListener("click", () => downloadSnapshot());

    // Mode buttons
    $("#toggle-mode-v5").addEventListener("click", () => setMode("V5"));
    $("#toggle-mode-v6").addEventListener("click", () => setMode("AIV6"));
    $("#toggle-mode-v7").addEventListener("click", () => setMode("AIV7"));

    // Tenant switcher
    const selTenant = $("#tenant-select");
    if (selTenant) selTenant.addEventListener("change", () => switchTenant(selTenant.value));

    // Self-repair
    $("#run-self-repair").addEventListener("click", () => runSelfRepair().catch(e => toast(e.message, "error")));
  }

  // ---------- Init ----------
  (function init() {
    bind();
    Promise.all([loadKpis(), loadLeads(), runSelfRepair()])
      .catch(e => toast(e.message, "error"));
  })();
})();
