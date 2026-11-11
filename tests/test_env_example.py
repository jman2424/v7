"""env.example must name every environment variable the application reads."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
READ = re.compile(r"""(?:getenv|environ\.get|_get|_env_int|_env_float|_env)\(\s*['"]([A-Z][A-Z0-9_]+)|environ\[['"]([A-Z][A-Z0-9_]+)""")
# Set by the host, by the app itself, or deliberately unsupported in deployments.
INTERNAL = {
    "RENDER", "RENDER_EXTERNAL_HOSTNAME", "V7_PRELOAD_MASTER_PID", "GITHUB_WORKSPACE", "FLASK_DEBUG",
    "PADDLE_API_KEY", "PADDLE_API_BASE", "PADDLE_WEBHOOK_SECRET",
}


def test_every_environment_variable_is_documented():
    used = set()
    for folder in ("app", "routes", "service", "retrieval", "connectors", "handlers", "scripts"):
        for path in (ROOT / folder).rglob("*.py"):
            for match in READ.finditer(path.read_text(encoding="utf-8")):
                used.add(match.group(1) or match.group(2))
    for name in ("brain_v7.py", "renderer_v7.py", "gunicorn.conf.py"):
        path = ROOT / name
        if path.exists():
            used.update(a or b for a, b in READ.findall(path.read_text(encoding="utf-8")))
    documented = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", (ROOT / "env.example").read_text(encoding="utf-8"), re.M))
    assert sorted(used - documented - INTERNAL) == []
