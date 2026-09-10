(() => {
  const select = document.getElementById("theme");
  let mode = "system";
  try { mode = localStorage.getItem("admin_theme") || "system"; } catch {}
  const apply = () => document.documentElement.dataset.theme = mode === "system" ? (matchMedia("(prefers-color-scheme:dark)").matches ? "dark" : "light") : mode;
  apply(); if (select) { select.value = mode; select.onchange = () => { mode = select.value; apply(); try {localStorage.setItem("admin_theme",mode);} catch {} }; }
})();
