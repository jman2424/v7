# @aisales/assistant-widget

Minimal JS SDK to embed the **AI Sales Assistant** as a web widget (iframe).

## Quick Start

```html
<div id="assistant-mount" style="width:380px;height:520px;"></div>
<script type="module">
  import { AssistantWidget } from "https://cdn.yoursite/assistant-widget/index.js";

  const mount = document.getElementById("assistant-mount");
  const widget = new AssistantWidget({
    baseUrl: "https://your-app.example.com",
    tenantKey: "EXAMPLE",
    container: mount
  });

  widget.on("ready", () => console.log("widget ready"));
  widget.on("message", (m) => console.log("assistant:", m.reply));
  widget.on("error", (e) => console.error("assistant error:", e));

  widget.open();
  widget.sendMessage("Hi, what are today’s hours?");
</script>
