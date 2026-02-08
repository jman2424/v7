let chartVolume, chartIntents, chartFallbacks;

function destroy(c){ if(c) c.destroy(); }

async function loadAnalytics(){
  const tenant = new URLSearchParams(location.search).get("tenant") || "DEFAULT";
  const res = await fetch(`/admin/api/analytics?tenant=${tenant}`, {
    credentials: "include"
  });
  const data = await res.json();

  const ts = data.timeseries || [];
  const intents = data.top_intents || [];
  const fallbacks = data.fallbacks || [];
  const k = data.kpis || {};

  document.getElementById("meta-volume").textContent =
    `Inbound ${k.inbound} • Outbound ${k.outbound} • Fallbacks ${k.fallbacks}`;

  document.getElementById("meta-intents").textContent =
    `${intents.reduce((a,x)=>a+x.count,0)} replies`;

  document.getElementById("meta-fallbacks").textContent =
    `${k.fallbacks} total`;

  renderVolume(ts);
  renderIntents(intents);
  renderFallbacks(fallbacks);
}

/* ------------------ CHARTS ------------------ */

function renderVolume(rows){
  destroy(chartVolume);
  chartVolume = new Chart(
    document.getElementById("chart-volume"),
    {
      type: "line",
      data: {
        labels: rows.map(r => r.t),
        datasets: [
          {
            label: "Inbound",
            data: rows.map(r => r.inbound),
            tension: 0.25
          },
          {
            label: "Outbound",
            data: rows.map(r => r.outbound),
            tension: 0.25
          }
        ]
      },
      options: {
        responsive: true,
        interaction: { mode: "index", intersect: false },
        scales: {
          y: { beginAtZero: true, ticks: { precision: 0 } }
        }
      }
    }
  );
}

function renderIntents(items){
  destroy(chartIntents);
  chartIntents = new Chart(
    document.getElementById("chart-intents"),
    {
      type: "doughnut",
      data: {
        labels: items.map(i => i.label),
        datasets: [{ data: items.map(i => i.count) }]
      },
      options: {
        cutout: "65%",
        plugins: { legend: { position: "bottom" } }
      }
    }
  );
}

function renderFallbacks(items){
  destroy(chartFallbacks);
  chartFallbacks = new Chart(
    document.getElementById("chart-fallbacks"),
    {
      type: "bar",
      data: {
        labels: items.map(i => i.label),
        datasets: [{
          label: "Fallbacks",
          data: items.map(i => i.count)
        }]
      },
      options: {
        indexAxis: "y",
        scales: {
          x: { beginAtZero: true, ticks: { precision: 0 } }
        },
        plugins: { legend: { display: false } }
      }
    }
  );
}

loadAnalytics().catch(console.error);
