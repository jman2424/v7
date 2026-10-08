"""Optional analytics configuration for the explicit public marketing allowlist."""
from flask import current_app, request

from app.config import valid_ga4_measurement_id
from service.public_site_content import SOLUTIONS


def measurement_id_for_request() -> str:
    public_page = request.endpoint == "root" or (
        request.endpoint == "public_seo.solution_page"
        and (request.view_args or {}).get("slug") in SOLUTIONS
    )
    if not public_page:
        return ""
    return valid_ga4_measurement_id(
        getattr(current_app.container.settings, "GA4_MEASUREMENT_ID", "")
    )
