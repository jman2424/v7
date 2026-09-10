(() => {
  const tenant = document.body.dataset.tenant;
  const status = document.getElementById("integration-status");
  if (status) fetch("/admin/api/integrations?tenant=" + encodeURIComponent(tenant), {credentials:"same-origin"})
    .then(response => { if (!response.ok) throw new Error(); return response.json(); })
    .then(data => { status.textContent = data.meta_configured || data.twilio_configured ? "Credentials configured. Complete provider verification and send a test message before launch." : data.whatsapp_assigned ? "Not connected yet. Website chat remains available." : "WhatsApp is not assigned to this company in this deployment."; })
    .catch(() => { status.textContent = "Unable to check integration status. Try signing in again."; });
  const list = document.getElementById("conversation-list");
  const more = document.getElementById("messages-more");
  let before = null, busy = false;
  async function messages() {
    if (busy) return; busy = true; more.disabled = true;
    try {
      const minutes = document.getElementById("period")?.value || "1440";
      const response = await fetch("/admin/api/conversations?tenant=" + encodeURIComponent(tenant) + "&minutes=" + minutes + (before ? "&before=" + before : ""), {credentials:"same-origin"});
      if (!response.ok) throw new Error();
      const data = await response.json();
      if (!data.messages.length && !before) list.textContent = "No messages recorded yet.";
      for (const item of data.messages) {
        const row = document.createElement("article"); row.className = "conversation-message";
        const heading = document.createElement("strong");
        heading.textContent = (item.event_type === "msg_in" ? "Customer" : "Agent") + " · " + item.channel + " · " + new Date(item.ts_utc).toLocaleString();
        const text = document.createElement("p"); text.textContent = item.text;
        row.append(heading, text); list.append(row);
      }
      before = data.next_before; more.hidden = !data.has_more;
    } catch { const error = document.createElement("p"); error.textContent = "Messages could not be loaded. Sign in again or retry."; list.append(error); }
    finally { busy = false; more.disabled = false; }
  }
  if (list) {
    const reload = () => { if (busy) return; before = null; list.replaceChildren(); messages(); };
    more.onclick = messages;
    document.getElementById("refresh")?.addEventListener("click", reload);
    document.getElementById("period")?.addEventListener("change", reload);
    messages();
  }
  const check = document.getElementById("check-health");
  if (check) check.onclick = async () => {
    const target = document.getElementById("health-results");
    check.disabled = true; target.textContent = "Checking…";
    try {
      const response = await fetch("/__diag/validate?tenant=" + encodeURIComponent(tenant), {credentials:"same-origin"});
      if (!response.ok) throw new Error();
      const data = await response.json(); target.replaceChildren();
      for (const [name, result] of Object.entries(data.validation.files)) {
        const row = document.createElement("p"); row.textContent = name + ": " + (!result.exists ? "Missing" : result.valid ? "Valid" : "Needs attention — check the saved format"); target.append(row);
      }
    } catch { target.textContent = "The data check could not be completed. Please retry."; }
    finally { check.disabled = false; }
  };
})();
