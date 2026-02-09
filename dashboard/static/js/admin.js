/* dashboard/static/js/admin.js
   Admin dashboard controller:
   - Fetches /admin/api/insights
   - Populates KPIs + tables
   - Calls window.DashChartsReload() for charts
   - Refresh + period change supported
*/

(function () {
  let abortCtl = null;

  function $(id) {
    return document.getElementById(id);
  }

  function tenant() {
    return (
      window.__ADMIN__?.tenant ||
      document.body?.dataset?.tenant ||
      "default"
    );
  }

  function minutes() {
    const sel = $("period");
    const v = sel ? parseInt(sel.value, 10) : 1440;
    return Number.isFinite(v) && v > 0 ? v : 1440;
  }

  function setText(id, value) {
    const el = $(id);
    if (el) el.textContent = String(value ?? "0");
  }

  function esc(s) {
    return String(s ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;");
  }

  async function fetchInsights() {
    if (abortCtl) abortCtl.abort();
    abortCtl = new AbortController();

    const url =
      `/admin/api/insights?tenant=${encodeURIComponent(tenant())}` +
      `&minutes=${encodeURIComponent(minutes())}` +
      `&bucket=60&top=10&limit=50`;

    const res = await fetch(url, {
      credentials: "include",
      signal: abortCtl.signal,
      headers: { Accept: "application/json" },
    });

    if (!res.ok) {
      const t = await res.text().catch(() => "");
      throw new Error(`Insights HTTP ${res.status}: ${t.slice(0, 200)}`);
    }
    return res.json();
  }

  function renderKpis(kpis) {
    setText("kpi-in", kpis?.inbound ?? 0);
    setText("kpi-out", kpis?.outbound ?? 0);
    setText("kpi-total", kpis?.total ?? 0);
    setText("kpi-sessions", kpis?.sessions ?? 0);
    setText("kpi-fb", kpis?.fallbacks ?? 0);
    setText("kpi-err", kpis?.errors ?? 0);
  }

  function renderQuestions(rows) {
    const tbody = $("tbl-questions");
    if (!tbody) return;

    if (!Array.isArray(rows) || rows.length === 0) {
      tbody.innerHTML = `<tr><td colspan="2">No data</td></tr>`;
      return;
    }

    tbody.innerHTML = rows
      .map((r) => {
        const q = esc(r?.question ?? "");
        const n = Number(r?.count ?? 0) || 0;
        return `<tr><td>${q}</td><td style="width:70px;">${n}</td></tr>`;
      })
      .join("");
  }

  function renderLeads(rows) {
    const tbody = $("tbl-leads");
    if (!tbody) return;

    if (!Array.isArray(rows) || rows.length === 0) {
      tbody.innerHTML = `<tr><td colspan="5">No leads yet</td></tr>`;
      return;
    }

    tbody.innerHTML = rows
      .map((r) => {
        const updated = esc((r?.updated_utc ?? "").replace("T", " ").replace("+00:00", "Z"));
        const name = esc(r?.name ?? "");
        const phone = esc(r?.phone ?? "");
        const status = esc(r?.status ?? "Open");
        const tags = Array.isArray(r?.tags) ? r.tags.map(esc).join(", ") : "";
        return `
          <tr>
            <td style="width:120px;">${updated}</td>
            <td style="width:140px;">${name}</td>
            <td style="width:130px;">${phone}</td>
            <td style="width:90px;">${status}</td>
            <td>${tags}</td>
          </tr>
        `;
      })
      .join("");
  }

  async function reloadAll() {
    const dbg = $("raw");
    const dbgStatus = $("dbg-status");
    if (dbgStatus) dbgStatus.textContent = "loading…";

    let payload;
    try {
      payload = await fetchInsights();
    } catch (err) {
      if (String(err).includes("AbortError")) return;
      console.error("admin.js insights fetch failed:", err);
      if (dbgStatus) dbgStatus.textContent = "fetch failed";
      if (dbg) dbg.textContent = String(err);
      return;
    }

    if (dbgStatus) dbgStatus.textContent = "ok";
    if (dbg) dbg.textContent = JSON.stringify(payload, null, 2);

    renderKpis(payload?.kpis || {});
    renderQuestions(payload?.common_questions || []);
    renderLeads(payload?.leads || []);

    // Charts are rendered by charts.js
    if (typeof window.DashChartsReload === "function") {
      window.DashChartsReload();
    }
  }

  async function exportCsv() {
    // Uses your existing exporter route if you have it (adjust if different).
    const url =
      `/admin/api/insights?tenant=${encodeURIComponent(tenant())}` +
      `&minutes=${encodeURIComponent(minutes())}` +
      `&bucket=60&top=200&limit=500`;

    try {
      const res = await fetch(url, { credentials: "include" });
      const payload = await res.json();

      // Simple CSV: questions + leads snapshot
      const lines = [];
      lines.push("SECTION,FIELD1,FIELD2,FIELD3");

      for (const q of (payload?.common_questions || [])) {
        lines.push(`questions,"${String(q.question ?? "").replaceAll('"', '""')}",${Number(q.count ?? 0) || 0},`);
      }
      for (const l of (payload?.leads || [])) {
        lines.push(`leads,"${String(l.lead_id ?? "").replaceAll('"', '""')}","${String(l.phone ?? "").replaceAll('"', '""')}","${String(l.updated_utc ?? "").replaceAll('"', '""')}"`);
      }

      const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `analytics_${tenant()}_${minutes()}m.csv`;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e) {
      console.error("export failed", e);
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    const refresh = $("refresh");
    const period = $("period");
    const exportBtn = $("export");

    if (refresh) refresh.addEventListener("click", reloadAll);
    if (period) period.addEventListener("change", reloadAll);
    if (exportBtn) exportBtn.addEventListener("click", exportCsv);

    reloadAll();
  });

  // expose for manual debugging
  window.AdminReloadAll = reloadAll;
})();
