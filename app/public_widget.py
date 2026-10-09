"""Optional website assistant for the explicit public marketing routes."""
from flask import current_app, request

from app.config import valid_public_widget_tenant
from service.public_site_content import SOLUTIONS


def widget_tenant_for_request() -> str:
    public_page = request.endpoint in {
        "root", "public_seo.about_page", "public_seo.setup_guide",
    } or (
        request.endpoint == "public_seo.solution_page"
        and (request.view_args or {}).get("slug") in SOLUTIONS
    )
    if not public_page:
        return ""
    return valid_public_widget_tenant(
        getattr(current_app.container.settings, "PUBLIC_WIDGET_TENANT", "")
    )
