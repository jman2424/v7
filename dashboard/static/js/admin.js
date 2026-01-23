/* static/js/admin.js
   Admin controller: KPIs debug + Leads + CSV export + Self-repair (optional)
   Charts are handled in admin_charts.js via window.DashChartsReload().
*/
(function () {
  const S = window.__ADMIN__ || {};
  const CSRF = S.csrfToken || "";
  const TENANT = (S.tenant || "").trim();

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  function withTenant(path) {
    try {
      const u = new URL(path, window.location.origin);
      if (TENANT && !u.searchParams.get("tenant")) u.searchParams.set("tenant", TENANT);
      return u.toString();
    } catch (_) {
      if (!TENANT) return path;
      return path.includes("?")
        ? `${path}&tenant=${encodeURIComponent(TENANT)}`
        : `${path}?tenant=${encodeURIComponent(TENANT)}`;
    }
  }

  function toast(msg, type = "ok") {
    const tpl = $("#toast-template");
    if (!tpl) { console.log(`[${type}]`, msg); return; }

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

    const txt = await res.text().catch(() => "");
    if (!res.ok) throw new Error(`HTTP ${res.status}: ${txt || res.statusText}`);

    try { return JSON.parse(txt); }
    catch { return { ok: true, raw: txt }; }
  }

  function escapeHtml(s) {
    return (s ?? "").toString()
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  async function loadLeads() {
    const tbody = $("#leads-table tbody");
    if (!tbody) return;

    tbody.innerHTML = `<tr><td colspan="6">Loading…</td></tr>`;

    const data = await apiJSON(`/admin/api/leads?limit=50`);
    const items = data.items || [];

    if (!items.length) {
      tbody.innerHTML = `<tr><td colspan="6">No leads yet.</td></tr>`;
      return;
    }

    tbody.innerHTML = items.slice(0, 60).map(l => `
      <tr>
        <td>${escapeHtml((l.updated_utc || "").slice(0,19).replace("T"," "))}</td>
        <td>${escapeHtml(l.name || "")}</td>
        <td>${escapeHtml(l.phone || "")}</td>
        <td>${escapeHtml(l.status || "")}</td>
        <td>${escapeHtml(l.tags || "")}</td>
        <td>${escapeHtml(l.last_session_id || "")}</td>
      </tr>
    `).join("");
  }

  function exportLeadsCSV() {
    window.location.href = withTenant(`/admin/api/leads.csv`);
  }

  async function runSelfRepair() {
    // Optional endpoint - don’t break UI if missing
    try {
      await apiJSON("/__diag/self_repair");
    } catch (_) {}
  }

  async function refreshAll() {
    const dbg = document.getElementById("dbg-status");
    const pre = document.getElementById("kpi-output");
    if (dbg) dbg.textContent = "Loading…";

    try {
      // Charts + KPI numbers + common questions are handled by admin_charts.js
      if (window.DashChartsReload) await window.DashChartsReload();

      // Leads table uses separate endpoint
      await loadLeads();

      // Optional maintenance
      await runSelfRepair();

      if (dbg) dbg.textContent = "OK";
    } catch (e) {
      if (dbg) dbg.textContent = "ERROR";
      if (pre) pre.textContent = String(e?.message || e);
      toast(String(e?.message || e), "error");
    }
  }

  function bind() {
    $("#refresh-kpis")?.addEventListener("click", refreshAll);
    $("#period-select")?.addEventListener("change", refreshAll);
    $("#export-leads")?.addEventListener("click", exportLeadsCSV);
  }

  window.addEventListener("DOMContentLoaded", () => {
    bind();
    refreshAll();

    // optional: show tenant once (remove if annoying)
    // if (TENANT) toast(`Tenant: ${TENANT}`, "warn");
  });
})();
