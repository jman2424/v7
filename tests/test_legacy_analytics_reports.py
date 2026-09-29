"""Legacy records retain message counts without breaking or inventing timing."""
from datetime import datetime, timedelta, timezone
import json

import pytest

from service import analytics_db
from service.statistics import get_statistics


def _legacy_rows(tenant, now):
    day = (now - timedelta(days=1)).date().isoformat()
    return [
        (day+'T10:00:00+00:00', tenant, 'msg_in', 'valid', json.dumps({'store':'London'})),
        (day+'T10:00:04+00:00', tenant, 'msg_out', 'valid:out', '{}'),
        (day+'T11:00:00-invalid', tenant, 'msg_in', 'invalid-in', 'invalid legacy json'),
        (day+'T11:00:05+00:00', tenant, 'msg_out', 'invalid-in:out', '{}'),
        (day+'T12:00:00+00:00', tenant, 'msg_in', 'invalid-out', ''),
        (day+'T12:00:05-invalid', tenant, 'msg_out', 'invalid-out:out', '{}'),
    ]


def _assert_reports(tenant, now):
    report = get_statistics(tenant=tenant, days=2, now=now)
    timing = report['replies']['total']
    assert timing['inbound'] == timing['eligible'] == timing['replied'] == 3
    assert timing['answered'] == 3
    assert timing['timed_replies'] == 1
    assert timing['response_seconds'] == pytest.approx(4, abs=0.001)
    assert report['replies']['daily'][0]['timed_replies'] == 1
    stores = {row['store']:row['count'] for row in
              analytics_db.get_whatsapp_store_share(tenant=tenant, minutes=4320)}
    assert stores == {'London':1, 'international':2}


def test_sqlite_reports_keep_malformed_legacy_records(app):
    now = datetime.now(timezone.utc)
    analytics_db._ensure_ready()
    with analytics_db._conn() as db:
        for row in _legacy_rows('EXAMPLE', now):
            db.execute("INSERT INTO events(ts_utc,tenant,event_type,message_id,meta_json,"
                       "channel,session_id,intent) VALUES(?,?,?,?,?,'whatsapp','customer','faq')", row)
    _assert_reports('EXAMPLE', now)


def test_postgres_reports_keep_malformed_legacy_records(pg_runtime):
    now = datetime.now(timezone.utc)
    tenant = pg_runtime['tenant']
    for row in _legacy_rows(tenant, now):
        pg_runtime['admin'].execute("INSERT INTO v7_private.events(ts_utc,tenant,event_type,"
            "message_id,meta_json,channel,session_id,intent) "
            "VALUES(%s,%s,%s,%s,%s,'whatsapp','customer','faq')", row)
    _assert_reports(tenant, now)
    assert analytics_db.get_whatsapp_store_share(tenant=pg_runtime['other'], minutes=4320) == []
