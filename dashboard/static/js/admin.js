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

  function isObj(x) {
    return x && typeof x === "object" && !Array.isArray(x);
  }

  function asArray(x) {
    return Array.isArray(x) ? x : [];
  }

  // Accept arrays, dicts, nulls. Dict -> [{key, ...value}]
  function toKeyedArray(x) {
    if (Array.isArray(x)) return x;
    if (isObj(x)) {
      return Object.entries(x).map(([k, v]) => {
        if (isObj(v)) return { key: k, ...v };
        return { key: k, value: v };
      });
    }
    return [];
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
    return {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
    };
  }

  function renderBar(canvasId, key, labels, values) {
    destroyChart(key);
    const ctx = $(canvasId);
    if (!ctx) return;

    const v = asArray(values).map(int);

    state.charts[key] = new Chart(ctx, {
      type: "bar",
      data: {
        labels: asArray(labels),
        datasets: [
          {
            label: "Count",
            data: v,
          },
        ],
      },
      options: Object.assign(chartBaseOpts(), {
        plugins: { legend: { display: false } },
        scales: {
          y: { beginAtZero: true, ticks: { callback: (x) => int(x) } },
          x: { ticks: { maxRotation: 0 } },
        },
      }),
    });
  }

  function renderPie(canvasId, key, labels, values) {
    destroyChart(key);
    const ctx = $(canvasId);
    if (!ctx) return;

    state.charts[key] = new Chart(ctx, {
      type: "pie",
      data: {
        labels: asArray(labels),
        datasets: [{ data: asArray(values).map(int) }],
      },
      options: Object.assign(chartBaseOpts(), {
        plugins: { legend: { position: "bottom" } },
      }),
    });
  }

  function renderLine(canvasId, key, labels, a, b) {
    destroyChart(key);
    const ctx = $(canvasId);
    if (!ctx) return;

    state.charts[key] = new Chart(ctx, {
      type: "line",
      data: {
        labels: asArray(labels),
        datasets: [
          { label: "Inbound", data: asArray(a).map(int), tension: 0.25, pointRadius: 0 },
          { label: "Outbound", data: asArray(b).map(int), tension: 0.25, pointRadius: 0 },
        ],
      },
      options: Object.assign(chartBaseOpts(), {
        plugins: { legend: { position: "bottom" } },
        scales: { y: { beginAtZero: true, ticks: { callback: (x) => int(x) } } },
      }),
    });
  }

  function renderSessionsLine(canvasId, key, labels, sessions) {
    destroyChart(key);
    const ctx = $(canvasId);
    if (!ctx) return;

    state.charts[key] = new Chart(ctx, {
      type: "line",
      data: {
        labels: asArray(labels),
        datasets: [{ label: "Sessions", data: asArray(sessions).map(int), tension: 0.25, pointRadius: 0 }],
      },
      options: Object.assign(chartBaseOpts(), {
        plugins: { legend: { display: false } },
        scales: { y: { beginAtZero: true, ticks: { callback: (x) => int(x) } } },
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

  // normalize insights payload from different backend versions
  function normalizeInsights(ins) {
    ins = ins || {};

    // channels:
    // - might be array [{key,count}] OR array [{label,inbound,outbound,total}] OR dict {web:{inbound,...}}
    let channels = [];
    if (Array.isArray(ins.channels)) {
      channels = ins.channels;
    } else if (isObj(ins.channels)) {
      channels = toKeyedArray(ins.channels).map((x) => ({
        label: x.label || x.key || "unknown",
        inbound: int(x.inbound),
        outbound: int(x.outbound),
        total: int(x.total ?? (int(x.inbound) + int(x.outbound))),
      }));
    } else if (Array.isArray(ins.channel_split)) {
      channels = ins.channel_split;
    }

    // If channels are in {key,count} format, keep as-is for pie.
    // If channels are inbound/outbound format, we can pie by total.
    const channelsForPie = channels.map((x) => {
      if ("count" in (x || {})) {
        return { key: x.key ?? x.label ?? "unknown", count: int(x.count) };
      }
      const label = x.label ?? x.key ?? "unknown";
      const total = int(x.total ?? (int(x.inbound) + int(x.outbound)));
      return { key: label, count: total };
    });

    // intents/fallbacks/errors may come as arrays with {key,count} or {label,count}
    function normalizeKeyCount(list) {
      const a = toKeyedArray(list);
      return a.map((x) => ({
        key: x.key ?? x.label ?? x.intent ?? x.code ?? "unknown",
        count: int(x.count ?? x.n ?? x.value ?? 0),
      }));
    }

    const intents = normalizeKeyCount(ins.intents || ins.top_intents);
    const fallbacks = normalizeKeyCount(ins.fallbacks || ins.top_fallbacks);
    const errors = normalizeKeyCount(ins.errors || ins.top_errors);

    const commonQuestionsRaw = ins.common_questions || ins.questions || [];
    const common_questions = toKeyedArray(commonQuestionsRaw).map((x) => ({
      text: x.text ?? x.question ?? x.q ?? x.key ?? "",
      count: int(x.count ?? x.n ?? 0),
    }));

    return { channelsForPie, intents, fallbacks, errors, common_questions };
  }

  async function refreshAll() {
    const minutes = Math.max(1, parseInt(($("period")?.value || "1440"), 10) || 1440);
    const dbg = $("dbg-status");
    const raw = $("raw");

    if (dbg) dbg.textContent = "Loading…";

    // Get everything in parallel, but fail gracefully per-section
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

    // KPIs: accept both total_messages and total
    $("kpi-in").textContent = int(k.inbound);
    $("kpi-out").textContent = int(k.outbound);

    const total = k.total_messages ?? k.total ?? (int(k.inbound) + int(k.outbound));
    $("kpi-total").textContent = int(total);

    $("kpi-sessions").textContent = int(k.sessions);
    $("kpi-fb").textContent = int(k.fallbacks);
    $("kpi-err").textContent = int(k.errors);

    const usedMinutes = k.minutes ?? minutes;
    $("kpi-sub").textContent = `Last ${int(usedMinutes)} minutes • bucket 60m`;

    // Timeseries: accept {points:[...]} or direct array
    const points = Array.isArray(ts.points) ? ts.points : (Array.isArray(ts) ? ts : []);
    const labels = points.map((p) => safeText(p.t || p.bucket || "").slice(5, 16).replace("T", " "));
    const inb = points.map((p) => int(p.inbound));
    const outb = points.map((p) => int(p.outbound));
    const sess = points.map((p) => int(p.sessions));

    renderLine("chart-volume", "volume", labels, inb, outb);
    renderSessionsLine("chart-sessions", "sessions", labels, sess);

    // Insights normalize
    const ins = normalizeInsights(insRaw);

    const ch = topN(ins.channelsForPie, 8);
    renderPie("chart-channels", "channels", ch.map((x) => x.key), ch.map((x) => x.count));

    const intents = topN(ins.intents, 10);
    renderBar("chart-intents", "intents", intents.map((x) => x.key), intents.map((x) => x.count));

    const fbs = topN(ins.fallbacks, 10);
    renderBar("chart-fallbacks", "fallbacks", fbs.map((x) => x.key), fbs.map((x) => x.count));

    const errs = topN(ins.errors, 10);
    renderBar("chart-errors", "errors", errs.map((x) => x.key), errs.map((x) => x.count));

    renderQuestions(ins.common_questions);
    renderLeads(ld.items || ld.leads || ld || []);

    if (raw) {
      raw.textContent = JSON.stringify(
        {
          tenant: TENANT,
          minutes,
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
