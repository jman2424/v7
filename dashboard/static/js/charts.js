/* Dependency-free charts: text values remain available to assistive technology. */
(() => {
  function bars(id, rows, title) {
    const chart = document.getElementById(id);
    if (!chart) return;
    chart.replaceChildren(); chart.setAttribute("aria-label", title);
    if (!rows.length) { chart.textContent = "No recorded activity in this period."; return; }
    const max = Math.max(1, ...rows.map(row => Number(row.count) || 0));
    for (const row of rows) {
      const line = document.createElement("div"); line.className = "metric-row";
      const label = document.createElement("span"); label.textContent = row.label;
      const track = document.createElement("div"), bar = document.createElement("span");
      bar.className = "metric-bar"; bar.style.width = (100 * (Number(row.count) || 0) / max) + "%";
      track.append(bar);
      const count = document.createElement("span"); count.textContent = row.count;
      line.append(label, track, count); chart.append(line);
    }
  }
  window.DashChartsReload = payload => {
    bars("chart-volume", (payload.message_volume || []).map(row => ({label: row.t, count: (row.inbound || 0) + (row.outbound || 0)})), "Messages by hour");
    bars("chart-channels", payload.channels_total || [], "Messages by channel");
    bars("chart-intents", payload.top_intents || [], "Top intents");
    bars("chart-fallbacks", payload.fallbacks || [], "Fallbacks");
    bars("chart-errors", payload.errors || [], "Errors by code");
    bars("chart-sessions", Object.entries(payload.sessions_by_channel || {}).map(([label,count]) => ({label,count})), "Sessions by channel");
  };
})();
