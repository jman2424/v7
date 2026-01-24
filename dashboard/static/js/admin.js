/* static/js/admin.js
   Dashboard controller: KPIs + charts + tables + CSV export
*/
(function () {
  const S = window.__ADMIN__ || {};
  const CSRF = S.csrfToken || "";
  const TENANT = (S.tenant || "").trim() || "default";

  const $ = (id) => document.getElementById(id);

  const state = { charts: {} };

  function int(n) {
    const x = Number(n);
    return Number.isFinite(x) ? Math.trunc(x) : 0;
  }

  function withTenant(path) {
    try {
      const u = new URL(path, window.location.origin);
      if (TENANT && !u.searchParams.get("tenant")) u.searchParams.set("tenant", TENANT);
      return u.toString();
    } catch {
      if (!TENANT) return path;
      return path.includes("?")
        ? `${path}&tenant=${encodeURIComponent(TENANT)}`
        : `${path}?tenant=${encodeURIComponent(TENANT)}`;
    }
  }

  function headers() {
    const h = {};
    if (CSRF) h["X-CSRF-Token"] = CSRF;
    return h;
  }

  async function getJSON(path) {
    const url = withTenant(path);
    const res = await fetch(url, { credentials: "include", headers: headers(), cache: "no-store" });
    const txt = await res.text().catch(() => "");
    if (!res.ok) throw new Error(`HTTP ${res.status} ${url}\n${txt}`);
    try { return JSON.parse(txt); }
    catch { throw new Error(`Bad JSON from ${url}\n${txt}`); }
  }

  function destroyChart(key) {
    if (state.charts[key]) {
      state.charts[key].destroy();
      delete state.charts[key];
    }
  }

  function chartBaseOpts() {
    return {
      responsive: true,
      maintainAspectRatio: false,
      animation: false
    };
  }

  function renderBar(canvasId, key, labels, values) {
    destroyChart(key);
    const ctx = $(canvasId);
    if (!ctx) return;

    const v = (values || []).map(int);
    const hasData = v.some(x => x > 0);

    state.charts[key] = new Chart(ctx, {
      type: "bar",
      data: {
        labels: labels || [],
        datasets: [{
          label: "Count",
          data: v
        }]
      },
      options: Object.assign(chartBaseOpts(), {
        plugins: { legend: { display: false } },
        scales: {
          y: { beginAtZero: true, ticks: { callback: (x) => int(x) } },
          x: { ticks: { maxRotation: 0 } }
        }
      })
    });

    // If truly no data, still show a sane axis
    if (!hasData && labels && labels.length === 0) {
      // nothing else needed; chart renders empty cleanly
    }
  }

  function renderPie(canvasId, key, labels, values) {
    destroyChart(key);
    const ctx = $(canvasId);
    if (!ctx) return;

    state.charts[key] = new Chart(ctx, {
      type: "pie",
      data: {
        labels: labels || [],
        datasets: [{ data: (values || []).map(int) }]
      },
      options: Object.assign(chartBaseOpts(), {
        plugins: { legend: { position: "bottom" } }
      })
    });
  }

  function renderLine(canvasId, key, labels, a, b) {
    destroyChart(key);
    const ctx = $(canvasId);
    if (!ctx) return;

    state.charts[key] = new Chart(ctx, {
      type: "line",
      data: {
        labels: labels || [],
        datasets: [
          { label: "Inbound", data: (a || []).map(int), tension: 0.25, pointRadius: 0 },
          { label: "Outbound", data: (b || []).map(int), tension: 0.25, pointRadius: 0 }
        ]
      },
      options: Object.assign(chartBaseOpts(), {
        plugins: { legend: { position: "bottom" } },
        scales: { y: { beginAtZero: true, ticks: { callback: (x) => int(x) } } }
      })
    });
  }

  function renderSessionsLine(canvasId, key, labels, sessions) {
    destroyChart(key);
    const ctx = $(canvasId);
    if (!ctx) return;

    state.charts[key] = new Chart(ctx, {
      type: "line",
      data: {
        labels: labels || [],
        datasets: [{ label: "Sessions", data: (sessions || []).map(int), tension: 0.25, pointRadius: 0 }]
      },
      options: Object.assign(chartBaseOpts(), {
        plugins: { legend: { display: false } },
        scales: { y: { beginAtZero: true, ticks: { callback: (x) => int(x) } } }
      })
    });
  }

  function escapeHtml(s) {
    return String(s ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function renderQuestions(items) {
    const tbody = $("tbl-questions");
    if (!tbody) return;

    if (!items || !items.length) {
      tbody.innerHTML = `<tr><td colspan="2">No questions logged.</td></tr>`;
      return;
    }
    tbody.innerHTML = items.slice(0, 25).map(x =>
      `<tr><td>${escapeHtml(x.text || "")}</td><td>${int(x.count)}</td></tr>`
    ).join("");
  }

  function renderLeads(items) {
    const tbody = $("tbl-leads");
    if (!tbody) return;

    if (!items || !items.length) {
      tbody.innerHTML = `<tr><td colspan="5">No leads yet.</td></tr>`;
      return;
    }
    tbody.innerHTML = items.slice(0, 35).map(r =>
      `<tr>
        <td>${escapeHtml((r.updated_utc || "").slice(0, 19).replace("T", " "))}</td>
        <td>${escapeHtml(r.name || "")}</td>
        <td>${escapeHtml(r.phone || "")}</td>
        <td>${escapeHtml(r.status || "")}</td>
        <td>${escapeHtml(r.tags || "")}</td>
      </tr>`
    ).join("");
  }

  function topN(arr, n) {
    return (arr || []).slice(0, n);
  }

  async function refreshAll() {
    const minutes = parseInt(($("period")?.value || "1440"), 10);
    const dbg = $("dbg-status");
    const raw = $("raw");

    if (dbg) dbg.textContent = "Loading…";

    const [k, ts, ins, ld] = await Promise.all([
      getJSON(`/admin/api/kpis?minutes=${minutes}`),
      getJSON(`/admin/api/timeseries?minutes=${minutes}&bucket=60`),
      getJSON(`/admin/api/insights?minutes=${minutes}&top=20`),
      getJSON(`/admin/api/leads?limit=50`),
    ]);

    $("kpi-in").textContent = int(k.inbound);
    $("kpi-out").textContent = int(k.outbound);
    $("kpi-total").textContent = int(k.total_messages);
    $("kpi-sessions").textContent = int(k.sessions);
    $("kpi-fb").textContent = int(k.fallbacks);
    $("kpi-err").textContent = int(k.errors);
    $("kpi-sub").textContent = `Last ${int(k.minutes)} minutes • bucket 60m`;

    const points = ts.points || [];
    const labels = points.map(p => (p.t || "").slice(5, 16).replace("T", " "));
    const inb = points.map(p => int(p.inbound));
    const outb = points.map(p => int(p.outbound));
    const sess = points.map(p => int(p.sessions));

    renderLine("chart-volume", "volume", labels, inb, outb);
    renderSessionsLine("chart-sessions", "sessions", labels, sess);

    const ch = topN(ins.channels, 8);
    renderPie("chart-channels", "channels", ch.map(x => x.key), ch.map(x => x.count));

    const intents = topN(ins.intents, 10);
    renderBar("chart-intents", "intents", intents.map(x => x.key), intents.map(x => x.count));

    const fbs = topN(ins.fallbacks, 10);
    renderBar("chart-fallbacks", "fallbacks", fbs.map(x => x.key), fbs.map(x => x.count));

    const errs = topN(ins.errors, 10);
    renderBar("chart-errors", "errors", errs.map(x => x.key), errs.map(x => x.count));

    renderQuestions(ins.common_questions || []);
    renderLeads(ld.items || []);

    if (raw) raw.textContent = JSON.stringify({ kpis: k, timeseries: ts, insights: ins }, null, 2);
    if (dbg) dbg.textContent = "OK";
  }

  window.addEventListener("DOMContentLoaded", () => {
    $("refresh")?.addEventListener("click", () => refreshAll().catch(e => {
      if ($("dbg-status")) $("dbg-status").textContent = "ERROR";
      if ($("raw")) $("raw").textContent = String(e);
    }));

    $("period")?.addEventListener("change", () => refreshAll().catch(e => {
      if ($("dbg-status")) $("dbg-status").textContent = "ERROR";
      if ($("raw")) $("raw").textContent = String(e);
    }));

    $("export")?.addEventListener("click", () => {
      window.location.href = withTenant(`/admin/api/leads.csv`);
    });

    refreshAll().catch(e => {
      if ($("dbg-status")) $("dbg-status").textContent = "ERROR";
      if ($("raw")) $("raw").textContent = String(e);
    });
  });
})();
