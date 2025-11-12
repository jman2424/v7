/* Minimal canvas charts (no deps).
   Exposes: window.DashCharts = { line, bar, spark }
   Each returns an object with .update(data) and .clear()
*/

(function () {
  function $(sel, root = document) { return root.querySelector(sel); }

  function px(n) { return Math.round(n) + 0.5; }

  function clear(ctx, w, h) {
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = "#0c0f16";
    ctx.fillRect(0, 0, w, h);
  }

  function grid(ctx, w, h) {
    ctx.strokeStyle = "#1d2230";
    ctx.lineWidth = 1;
    ctx.setLineDash([2, 3]);
    for (let y = 0; y <= 4; y++) {
      const yy = px((h - 20) * (y / 4) + 10);
      ctx.beginPath();
      ctx.moveTo(10, yy);
      ctx.lineTo(w - 10, yy);
      ctx.stroke();
    }
    ctx.setLineDash([]);
  }

  function scaleY(values, h) {
    const min = 0;
    const max = Math.max(1, Math.max.apply(null, values));
    const scale = (v) => {
      const t = (v - min) / (max - min);
      return px((1 - t) * (h - 20) + 10);
    };
    return { min, max, scale };
  }

  function line(canvas, data) {
    const ctx = canvas.getContext("2d");
    const w = canvas.width, h = canvas.height;

    function render(series) {
      clear(ctx, w, h);
      grid(ctx, w, h);
      const values = series.map(d => d.count || d.value || 0);
      const { scale } = scaleY(values, h);
      const step = (w - 40) / Math.max(1, series.length - 1);

      ctx.strokeStyle = "#60a5fa";
      ctx.lineWidth = 2;
      ctx.beginPath();
      series.forEach((d, i) => {
        const x = px(20 + i * step);
        const y = scale(d.count || d.value || 0);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.stroke();

      // marker dots
      ctx.fillStyle = "#93c5fd";
      series.forEach((d, i) => {
        const x = px(20 + i * step);
        const y = scale(d.count || d.value || 0);
        ctx.beginPath();
        ctx.arc(x, y, 2.5, 0, Math.PI * 2);
        ctx.fill();
      });
    }

    render(data || []);

    return {
      update(next) { render(next || []); },
      clear() { clear(ctx, w, h); }
    };
  }

  function bar(canvas, data) {
    const ctx = canvas.getContext("2d");
    const w = canvas.width, h = canvas.height;

    function render(series) {
      clear(ctx, w, h);
      grid(ctx, w, h);
      const values = series.map(d => d.count || d.value || 0);
      const { scale, max } = scaleY(values, h);
      const pad = 18;
      const bw = Math.max(6, (w - pad * 2) / Math.max(1, series.length) - 6);

      series.forEach((d, i) => {
        const v = d.count || d.value || 0;
        const x = px(pad + i * (bw + 6));
        const y = scale(v);
        const hh = (h - 10) - y;
        ctx.fillStyle = "#34d399";
        ctx.fillRect(x, y, bw, hh);
      });
    }

    render(data || []);

    return {
      update(next) { render(next || []); },
      clear() { clear(ctx, w, h); }
    };
  }

  function spark(canvas, data) {
    // tiny inline timeseries (unused for now, ready if needed)
    const ctx = canvas.getContext("2d");
    const w = canvas.width, h = canvas.height;

    function render(vals) {
      clear(ctx, w, h);
      const { scale } = scaleY(vals, h);
      const step = (w - 20) / Math.max(1, vals.length - 1);
      ctx.strokeStyle = "#22c55e";
      ctx.beginPath();
      vals.forEach((v, i) => {
        const x = px(10 + i * step);
        const y = scale(v);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.stroke();
    }

    render(data || []);
    return { update: render, clear: () => clear(ctx, w, h) };
  }

  window.DashCharts = { line, bar, spark };
})();
