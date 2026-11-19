"""Exercise simultaneous requests across a full synthetic onboarding cohort."""
import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from math import ceil
from time import perf_counter

from flask.testing import FlaskClient


def test_thirty_businesses_answer_from_their_own_saved_knowledge(app, tmp_business):
    tenants = [f"COHORT{i:02d}" for i in range(30)]
    question = "Is everything halal?"
    for tenant in tenants:
        folder = tmp_business.parent / tenant
        shutil.copytree(tmp_business, folder)
        faq = [{"q": question, "a": f"Certification reference {tenant}.", "tags": ["halal"]}]
        (folder / "faq.json").write_text(json.dumps(faq), encoding="utf-8")

    def ask(tenant):
        with FlaskClient(app, app.response_class) as client:
            started = perf_counter()
            response = client.post("/chat_api", json={
                "tenant": tenant, "message": question,
                "channel": "web",
            }, environ_overrides={"REMOTE_ADDR": f"192.0.2.{1 + tenants.index(tenant)}"})
            assert response.status_code == 200, (tenant, response.status_code)
            reply = response.get_json()["reply"]
            assert [key for key in tenants if key in reply] == [tenant], (tenant, reply)

            return perf_counter() - started

    with ThreadPoolExecutor(max_workers=6) as pool:
        for phase in ("first chat", "repeat chat"):
            durations = sorted(pool.map(ask, tenants))
            p95 = durations[ceil(.95 * len(durations)) - 1]
            print(f"{phase}, 30 businesses, 6 workers, p95 {p95:.3f}s")
