/* dashboard/static/js/admin.js
   Single-file dashboard controller + charts.
   Works with dashboard/templates/dashboard.html IDs exactly.
*/
(function () {
  const csrf = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || "";
  const TENANT = (document.body?.dataset?.tenant || "").trim();

  const $ = (id) => document.getElementById(id);
  const state = { charts: {} };

  function int(n){
    const x = Number(n);
    return Number.isFinite(x) ? Math.trunc(x) : 0;
  }

  function headers(){
    const h = {};
    if (csrf) h["X-CSRF-Token"] = csrf;
    return h;
  }

  function withTenant(url){
    // url is relative like "/admin/api/kpis?minutes=1440"
    if (!TENANT) return url;
    return url.includes("?")
      ? `${url}&tenant=${encodeURIComponent(TENANT)}`
      : `${url}?tenant=${encodeURIComponent(TENANT)}`;
  }

  async function getJSON(url){
    const res = await fetch(withTenant(url), { credentials:"include", headers: headers() });
    const txt = await res.text();
    if(!res.ok) throw new Error(`HTTP ${res.status} ${url}\n${txt}`);
    try { return JSON.parse(txt); }
    catch { throw new Error(`Bad JSON from ${url}\n${txt}`); }
  }

  function destroyChart(key){
    if(state.charts[key]){ state.charts[key].destroy(); delete state.charts[key]; }
  }

  function showNoData(canvasId, msg){
    const canvas = $(canvasId);
    if(!canvas) return;
    const ctx = canvas.getContext("2d");
    if(!ctx) return;
    ctx.clearRect(0,0,canvas.width,canvas.height);
    ctx.save();
    ctx.fillStyle = "rgba(255,255,255,.6)";
    ctx.font = "12px system-ui, -apple-system, Segoe UI, Roboto, Arial";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(msg || "No data", canvas.width/2, canvas.height/2);
    ctx.restore();
  }

  function renderBar(canvasId, key, labels, values){
    destroyChart(key);
    if(!labels.length){
      showNoData(canvasId, "No data");
      return;
    }
    state.charts[key] = new Chart($(canvasId), {
      type: "bar",
      data: { labels, datasets: [{ label: "Count", data: values.map(int) }] },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { y: { ticks: { callback: (v)=>int(v) }, beginAtZero:true } }
      }
    });
  }

  function renderPie(canvasId, key, labels, values){
    destroyChart(key);
    if(!labels.length){
      showNoData(canvasId, "No data");
      return;
    }
    state.charts[key] = new Chart($(canvasId), {
      type: "pie",
      data: { labels, datasets: [{ data: values.map(int) }] },
      options: {
        responsive:true,
        maintainAspectRatio:false,
        plugins:{ legend:{ position:"bottom" } }
      }
    });
  }

  function renderLine(canvasId, key, labels, inbound, outbound){
    destroyChart(key);

    if(!labels.length){
      showNoData(canvasId, "No data");
      return;
    }

    const showPoints = labels.length <= 6 ? 3 : 0;

    state.charts[key] = new Chart($(canvasId), {
      type: "line",
      data: {
        labels,
        datasets: [
          { label: "Inbound", data: inbound.map(int), tension: 0.25, pointRadius: showPoints },
          { label: "Outbound", data: outbound.map(int), tension: 0.25, pointRadius: showPoints }
        ]
      },
      options: {
        responsive:true,
        maintainAspectRatio:false,
        plugins:{ legend:{ position:"bottom" } },
        scales:{ y:{ ticks:{ callback:(v)=>int(v) }, beginAtZero:true } }
      }
    });
  }

  function renderSessionsLine(canvasId, key, labels, sessions){
    destroyChart(key);

    if(!labels.length){
      showNoData(canvasId, "No data");
      return;
    }

    const showPoints = labels.length <= 6 ? 3 : 0;

    state.charts[key] = new Chart($(canvasId), {
      type: "line",
      data: { labels, datasets: [{ label: "Sessions", data: sessions.map(int), tension: 0.25, pointRadius: showPoints }] },
      options: {
        responsive:true,
        maintainAspectRatio:false,
        plugins:{ legend:{ display:false } },
        scales:{ y:{ ticks:{ callback:(v)=>int(v) }, beginAtZero:true } }
      }
    });
  }

  function escapeHtml(s){
    return String(s ?? "")
      .replaceAll("&","&amp;")
      .replaceAll("<","&lt;")
      .replaceAll(">","&gt;")
      .replaceAll('"',"&quot;")
      .replaceAll("'","&#039;");
  }

  function renderQuestions(items){
    const tbody = $("tbl-questions");
    if(!tbody) return;

    if(!items || !items.length){
      tbody.innerHTML = `<tr><td colspan="2">No questions logged.</td></tr>`;
      return;
    }

    tbody.innerHTML = items.slice(0,25).map(x =>
      `<tr><td>${escapeHtml(x.text || "")}</td><td>${int(x.count)}</td></tr>`
    ).join("");
  }

  function renderLeads(items){
    const tbody = $("tbl-leads");
    if(!tbody) return;

    if(!items || !items.length){
      tbody.innerHTML = `<tr><td colspan="5">No leads yet.</td></tr>`;
      return;
    }

    tbody.innerHTML = items.slice(0,35).map(r =>
      `<tr>
        <td>${escapeHtml((r.updated_utc || "").slice(0,19).replace("T"," "))}</td>
        <td>${escapeHtml(r.name || "")}</td>
        <td>${escapeHtml(r.phone || "")}</td>
        <td>${escapeHtml(r.status || "")}</td>
        <td>${escapeHtml(r.tags || "")}</td>
      </tr>`
    ).join("");
  }

  function topN(arr, n){ return (arr || []).slice(0,n); }

  function pickBucket(minutes){
    // ✅ makes the line chart actually move
    if (minutes <= 180) return 5;     // 3h → 5-min buckets (up to 36 points)
    if (minutes <= 1440) return 60;   // 24h → hourly
    return 240;                        // 7d/30d → 4-hour buckets
  }

  async function refreshAll(){
    const minutes = parseInt(($("period")?.value || "1440"), 10);
    const bucket = pickBucket(minutes);

    $("dbg-status").textContent = "Loading…";

    const [k, ts, ins, ld] = await Promise.all([
      getJSON(`/admin/api/kpis?minutes=${minutes}`),
      getJSON(`/admin/api/timeseries?minutes=${minutes}&bucket=${bucket}`),
      getJSON(`/admin/api/insights?minutes=${minutes}&top=20`),
      getJSON(`/admin/api/leads?limit=50`),
    ]);

    $("kpi-in").textContent = int(k.inbound);
    $("kpi-out").textContent = int(k.outbound);
    $("kpi-total").textContent = int(k.total_messages);
    $("kpi-sessions").textContent = int(k.sessions);
    $("kpi-fb").textContent = int(k.fallbacks);
    $("kpi-err").textContent = int(k.errors);
    $("kpi-sub").textContent = `Last ${int(k.minutes)} minutes • bucket ${bucket}m`;

    const labels = (ts.points || []).map(p => (p.t || "").slice(5,16).replace("T"," "));
    const inb = (ts.points || []).map(p => int(p.inbound));
    const outb = (ts.points || []).map(p => int(p.outbound));
    const sess = (ts.points || []).map(p => int(p.sessions));

    renderLine("chart-volume", "volume", labels, inb, outb);
    renderSessionsLine("chart-sessions", "sessions", labels, sess);

    const ch = topN(ins.channels, 8);
    renderPie("chart-channels", "channels", ch.map(x=>x.key), ch.map(x=>x.count));

    const intents = topN(ins.intents, 10);
    renderBar("chart-intents", "intents", intents.map(x=>x.key), intents.map(x=>x.count));
    $("sub-intents").textContent = intents.length ? "bar" : "no data";

    const fbs = topN(ins.fallbacks, 10);
    renderBar("chart-fallbacks", "fallbacks", fbs.map(x=>x.key), fbs.map(x=>x.count));
    $("sub-fallbacks").textContent = fbs.length ? "bar" : "no data";

    const errs = topN(ins.errors, 10);
    renderBar("chart-errors", "errors", errs.map(x=>x.key), errs.map(x=>x.count));
    $("sub-errors").textContent = errs.length ? "bar" : "no data";

    renderQuestions(ins.common_questions || []);
    renderLeads(ld.items || []);

    $("raw").textContent = JSON.stringify({kpis:k, timeseries:ts, insights:ins}, null, 2);
    $("dbg-status").textContent = "OK";
  }

  window.addEventListener("DOMContentLoaded", () => {
    $("refresh")?.addEventListener("click", () => refreshAll().catch(e => {
      $("dbg-status").textContent = "ERROR";
      $("raw").textContent = String(e);
    }));

    $("period")?.addEventListener("change", () => refreshAll().catch(e => {
      $("dbg-status").textContent = "ERROR";
      $("raw").textContent = String(e);
    }));

    $("export")?.addEventListener("click", () => {
      window.location.href = withTenant(`/admin/api/leads.csv`);
    });

    refreshAll().catch(e => {
      $("dbg-status").textContent = "ERROR";
      $("raw").textContent = String(e);
    });
  });
})();
