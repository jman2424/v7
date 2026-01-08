let chart;

async function fetchJSON(url) {
  const res = await fetch(url, { credentials: "include" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return await res.json();
}

async function renderTimeseries(minutes) {
  const data = await fetchJSON(`/admin/api/timeseries?minutes=${minutes}`);
  const points = data.points || [];

  const labels = points.map(p => p.t);
  const inbound = points.map(p => p.inbound);
  const outbound = points.map(p => p.outbound);

  const canvas = document.getElementById("chart-main");
  if (!canvas) return;

  if (chart) chart.destroy();

  chart = new Chart(canvas, {
    type: "line",
    data: {
      labels,
      datasets: [
        { label: "Inbound", data: inbound },
        { label: "Outbound", data: outbound }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false
    }
  });
}

window.addEventListener("DOMContentLoaded", async () => {
  const minutes = parseInt(document.getElementById("period-select")?.value || "1440", 10);
  try { await renderTimeseries(minutes); } catch (e) { console.error(e); }
  document.getElementById("period-select")?.addEventListener("change", async (ev) => {
    await renderTimeseries(parseInt(ev.target.value, 10));
  });
});
