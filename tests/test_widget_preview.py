"""The owner console previews the real widget in an inert mode that sends nothing."""
from pathlib import Path

WIDGET = Path(__file__).resolve().parents[1] / "dashboard/static/js/widget.js"


def test_preview_mode_is_only_enabled_for_an_embedded_panel(client):
    preview = client.get("/chat_ui?tenant=EXAMPLE&embed=panel&preview=1").get_data(as_text=True)
    assert "preview: true" in preview
    for url in ("/chat_ui?tenant=EXAMPLE", "/chat_ui?tenant=EXAMPLE&preview=1",
                "/chat_ui?tenant=EXAMPLE&embed=1&preview=1", "/chat_ui?tenant=EXAMPLE&embed=panel"):
        assert "preview: false" in client.get(url).get_data(as_text=True), url


def test_preview_accepts_restyling_only_from_its_own_site_and_never_sends():
    source = WIDGET.read_text(encoding="utf-8")
    block = source[source.index("if (config.preview) {\n    // Appearance preview"):source.index("  restoreTranscript();\n  let site")]
    assert "event.origin !== window.location.origin || event.source !== window.parent" in block
    assert "fetch(" not in block and "sessionStorage" not in block and "innerHTML" not in block
    assert block.rstrip().endswith("return;\n  }") or "return;\n  }" in block
    # The submit handler stops before any request in preview mode.
    submit = source[source.index('form.addEventListener("submit"'):]
    assert submit.index("if (config.preview)") < submit.index("fetch(")
