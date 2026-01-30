/* static/js/admin.js
   Dashboard controller: KPIs + charts + tables + CSV export

   FIXES:
   1) "Channels" pie is changed to INBOUND vs OUTBOUND (3 vs 3)
      - because you want direction share, not channel share.

   2) "Message Volume" is now a BAR chart (grouped: inbound/outbound)
      - so you get the “4 bars that grow” look.

   3) Timeseries label + bucket handling is robust:
      - supports p.t, p.bucket, p.hour_bucket, p.ts, p.time
      - doesn’t silently render empty labels

   4) Tenant is ALWAYS included via withTenant() (already existed)
      - keep using it, it’s correct.

   5) Debug panel now also shows the exact points we used.
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

  function isObj(x) {
    return x && typeof x === "object" && !Array.isArray(x);
  }

  function asArray(x) {
    return Array.isArray(x) ? x : [];
  }

  function safeText(x) {
    if (x === null || x === undefined) return "";
    if (typeof x === "string") return x;
    if (typeof x === "number" || typeof x === "boolean") return String(x);
    if (Array.isArray(x)) return x.map(safeText).filter(Boolean).join(", ");
    if (isObj(x)) return JSON.stringify(x);
    return String(x);
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
    try {
      return JSON.parse(txt);
    } catch {
      throw new Error(`Bad JSON from ${url}\n${txt}`);
    }
  }

  function destroyChart(key) {
    if (state.charts[key]) {
      state.charts[key].destroy();
      delete state.charts[key];
    }
  }

  function chartBaseOpts() {
    return { responsive: true, maintainAspectRatio: false, animation: false };
  }

  // ---------- Chart renderers ----------

  function renderBarSimple(canvasId, key, labels, values) {
    destroyChart(key);
    const canvas = $(canvasId);
    if (!canvas) return;

    const v = asArray(values).map(int);

    state.charts[key] = new Chart(canvas, {
      type: "bar",
      data: {
        labels: asArray(labels),
        datasets: [{ label: "Count", data: v }],
      },
      options: Object.assign(chartBaseOpts(), {
        plugins: { legend: { display: false } },
        scales: {
          y: { beginAtZero: true, ticks: { callback: (x) => int(x), stepSize: 1, precision: 0 } },
          x: { ticks: { maxRotation: 0 } },
        },
      }),
    });
  }

  // ✅ NEW: grouped bars for Message Volume (inbound/outbound)
  function renderVolumeBars(canvasId, key, labels, inbound, outbound) {
    destroyChart(key);
    const canvas = $(canvasId);
    if (!canvas) return;

    state.charts[key] = new Chart(canvas, {
      type: "bar",
      data: {
        labels: asArray(labels),
        datasets: [
          { label: "Inbound", data: asArray(inbound).map(int) },
          { label: "Outbound", data: asArray(outbound).map(int) },
        ],
      },
      options: Object.assign(chartBaseOpts(), {
        plugins: { legend: { position: "bottom" } },
        scales: {
          y: { beginAtZero: true, ticks: { callback: (x) => int(x), stepSize: 1, precision: 0 } },
          x: { ticks: { maxRotation: 0, autoSkip: true } },
        },
      }),
    });
  }

  // ✅ Direction pie (Inbound vs Outbound)
  function renderDirectionPie(canvasId, key, inboundCount, outboundCount) {
    destroyChart(key);
    const canvas = $(canvasId);
    if (!canvas) return;

    state.charts[key] = new Chart(canvas, {
      type: "pie",
      data: {
        labels: ["Inbound", "Outbound"],
        datasets: [{ data: [int(inboundCount), int(outboundCount)] }],
      },
      options: Object.assign(chartBaseOpts(), {
        plugins: { legend: { position: "bottom" } },
      }),
    });
  }

  function renderSessionsLine(canvasId, key, labels, sessions) {
    destroyChart(key);
    const canvas = $(canvasId);
    if (!canvas) return;

    state.charts[key] = new Chart(canvas, {
      type: "line",
      data: {
        labels: asArray(labels),
        datasets: [{ label: "Sessions", data: asArray(sessions).map(int), tension: 0.25, pointRadius: 0 }],
      },
      options: Object.assign(chartBaseOpts(), {
        plugins: { legend: { display: false } },
        scales: {
          y: { beginAtZero: true, ticks: { callback: (x) => int(x), stepSize: 1, precision: 0 } },
        },
      }),
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

    const arr = asArray(items);

    if (!arr.length) {
      tbody.innerHTML = `<tr><td colspan="2">No questions logged.</td></tr>`;
      return;
    }

    tbody.innerHTML = arr.slice(0, 25).map((x) => {
      const q = x?.question ?? x?.text ?? x?.q ?? "";
      const c = x?.count ?? x?.n ?? 0;
      return `<tr><td>${escapeHtml(q)}</td><td>${int(c)}</td></tr>`;
    }).join("");
  }

  function renderLeads(items) {
    const tbody = $("tbl-leads");
    if (!tbody) return;

    const arr = asArray(items);

    if (!arr.length) {
      tbody.innerHTML = `<tr><td colspan="5">No leads yet.</td></tr>`;
      return;
    }

    tbody.innerHTML = arr.slice(0, 35).map((r) => {
      const updated = safeText(r?.updated_utc || r?.updated || "").slice(0, 19).replace("T", " ");
      const name = safeText(r?.name || "");
      const phone = safeText(r?.phone || "");
      const status = safeText(r?.status || "");
      const tagsVal = r?.tags ?? r?.tags_any ?? "";
      const tags = Array.isArray(tagsVal) ? tagsVal.join(", ") : safeText(tagsVal);

      return `<tr>
        <td>${escapeHtml(updated)}</td>
        <td>${escapeHtml(name)}</td>
        <td>${escapeHtml(phone)}</td>
        <td>${escapeHtml(status)}</td>
        <td>${escapeHtml(tags)}</td>
      </tr>`;
    }).join("");
  }

  function topN(arr, n) {
    return asArray(arr).slice(0, n);
  }

  function normalizeKeyCount(list) {
    const arr = asArray(list);
    return arr.map((x) => ({
      key: x?.key ?? x?.label ?? x?.intent ?? x?.code ?? "unknown",
      count: int(x?.count ?? x?.n ?? x?.value ?? 0),
    }));
  }

  function normalizeInsights(ins) {
    ins = ins || {};
    const intents = normalizeKeyCount(ins.intents || ins.top_intents);
    const fallbacks = normalizeKeyCount(ins.fallbacks || ins.top_fallbacks);
    const errors = normalizeKeyCount(ins.errors || ins.top_errors);

    const commonQuestionsRaw = ins.common_questions || ins.questions || [];
    const common_questions = asArray(commonQuestionsRaw).map((x) => ({
      text: x?.text ?? x?.question ?? x?.q ?? x?.key ?? "",
      count: int(x?.count ?? x?.n ?? 0),
    }));

    return { intents, fallbacks, errors, common_questions };
  }

  // Robust bucket label formatter (aim: "MM-DD HH:MM" like your UI)
  function pointLabel(p) {
    const raw =
      p?.t ??
      p?.bucket ??
      p?.hour_bucket ??
      p?.ts ??
      p?.time ??
      "";

    const s = safeText(raw);
    if (!s) return "";

    // If it's ISO like "2026-01-30T01", slice to show "01-30 01"
    // If it's "2026-01-30T01:00:00Z" still works enough for display.
    return s.slice(5, 16).replace("T", " ");
  }

  async function refreshAll() {
    const minutes = Math.max(1, parseInt(($("period")?.value || "1440"), 10) || 1440);

    const dbg = $("dbg-status");
    const raw = $("raw");
    if (dbg) dbg.textContent = "Loading…";

    const results = await Promise.allSettled([
      getJSON(`/admin/api/kpis?minutes=${minutes}`),
      getJSON(`/admin/api/timeseries?minutes=${minutes}&bucket=60`),
      getJSON(`/admin/api/insights?minutes=${minutes}&top=20`),
      getJSON(`/admin/api/leads?limit=50`),
    ]);

    const k = results[0].status === "fulfilled" ? results[0].value : {};
    const ts = results[1].status === "fulfilled" ? results[1].value : {};
    const insRaw = results[2].status === "fulfilled" ? results[2].value : {};
    const ld = results[3].status === "fulfilled" ? results[3].value : {};

    // ----- KPIs -----
    const inboundK = int(k.inbound);
    const outboundK = int(k.outbound);

    $("kpi-in").textContent = inboundK;
    $("kpi-out").textContent = outboundK;

    const total = k.total_messages ?? k.total ?? (inboundK + outboundK);
    $("kpi-total").textContent = int(total);

    $("kpi-sessions").textContent = int(k.sessions);
    $("kpi-fb").textContent = int(k.fallbacks);
    $("kpi-err").textContent = int(k.errors);

    const usedMinutes = k.minutes ?? minutes;
    $("kpi-sub").textContent = `Last ${int(usedMinutes)} minutes • bucket 60m`;

    // ----- Timeseries -----
    const points = Array.isArray(ts.points) ? ts.points : (Array.isArray(ts) ? ts : []);
    const labels = points.map(pointLabel);
    const inb = points.map((p) => int(p.inbound));
    const outb = points.map((p) => int(p.outbound));
    const sess = points.map((p) => int(p.sessions));

    // ✅ Message Volume as BARS (not line)
    renderVolumeBars("chart-volume", "volume", labels, inb, outb);

    // Sessions chart stays line
    renderSessionsLine("chart-sessions", "sessions", labels, sess);

    // ----- Insights -----
    const ins = normalizeInsights(insRaw);

    const intents = topN(ins.intents, 10);
    renderBarSimple("chart-intents", "intents", intents.map((x) => x.key), intents.map((x) => x.count));

    const fbs = topN(ins.fallbacks, 10);
    renderBarSimple("chart-fallbacks", "fallbacks", fbs.map((x) => x.key), fbs.map((x) => x.count));

    const errs = topN(ins.errors, 10);
    renderBarSimple("chart-errors", "errors", errs.map((x) => x.key), errs.map((x) => x.count));

    renderQuestions(ins.common_questions);
    renderLeads(ld.items || ld.leads || ld || []);

    // ✅ Replace "Channels" pie with Direction (Inbound vs Outbound)
    // (this makes it show 3 vs 3 instead of web=6)
    renderDirectionPie("chart-channels", "direction", inboundK, outboundK);

    // ----- Debug -----
    if (raw) {
      raw.textContent = JSON.stringify(
        {
          tenant: TENANT,
          minutes,
          used_points: points.map((p) => ({
            label: pointLabel(p),
            inbound: int(p.inbound),
            outbound: int(p.outbound),
            sessions: int(p.sessions),
            raw_bucket: p?.bucket,
            raw_t: p?.t,
          })),
          kpis: k,
          timeseries: ts,
          insights: insRaw,
          leads: ld,
          warnings: results
            .map((r, i) => (r.status === "rejected" ? `Fetch ${i} failed: ${String(r.reason)}` : null))
            .filter(Boolean),
        },
        null,
        2
      );
    }

    if (dbg) {
      const anyFail = results.some((r) => r.status === "rejected");
      dbg.textContent = anyFail ? "PARTIAL" : "OK";
    }
  }

  window.addEventListener("DOMContentLoaded", () => {
    $("refresh")?.addEventListener("click", () =>
      refreshAll().catch((e) => {
        if ($("dbg-status")) $("dbg-status").textContent = "ERROR";
        if ($("raw")) $("raw").textContent = String(e);
      })
    );

    $("period")?.addEventListener("change", () =>
      refreshAll().catch((e) => {
        if ($("dbg-status")) $("dbg-status").textContent = "ERROR";
        if ($("raw")) $("raw").textContent = String(e);
      })
    );

    $("export")?.addEventListener("click", () => {
      window.location.href = withTenant(`/admin/api/leads.csv`);
    });

    refreshAll().catch((e) => {
      if ($("dbg-status")) $("dbg-status").textContent = "ERROR";
      if ($("raw")) $("raw").textContent = String(e);
    });
  });
})();
