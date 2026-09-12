from datetime import datetime, timedelta, timezone
import json

import pytest

from service import analytics_db
from service.statistics import get_statistics
from tests.conftest import set_test_identity


def test_statistics_window_channels_and_company_isolation(app):
    now = datetime(2026, 9, 12, 12, tzinfo=timezone.utc)
    analytics_db._ensure_ready()
    with analytics_db._conn() as db:
        def event(days, kind, channel='web', tenant='EXAMPLE', intent='faq', meta='{}', lead=''):
            db.execute('INSERT INTO events(ts_utc,tenant,channel,session_id,event_type,intent,text,meta_json,lead_id) VALUES(?,?,?,?,?,?,?,?,?)',
                       ((now-timedelta(days=days)).isoformat(),tenant,channel,'same-id',kind,intent,'PRIVATE CUSTOMER MESSAGE',meta,lead))
        event(1,'msg_in')
        event(1,'msg_out',meta=json.dumps({'fallback':True}))
        event(2,'msg_in',channel='whatsapp')
        event(2,'msg_out',channel='whatsapp',intent='human_handoff')
        event(2,'msg_out',channel='whatsapp',intent='handoff_contact_captured',lead='lead1')
        event(2,'msg_out',channel='whatsapp',intent='handoff_contact_captured',lead='lead1')
        event(3,'error',meta='invalid legacy json')
        event(7,'msg_in')  # Exact current-window boundary.
        event(8,'msg_in')
        event(14,'msg_in')  # Exact previous-window boundary.
        event(15,'msg_in')
        event(-1,'msg_in')  # Future event must not inflate the report.
        event(1,'msg_in',tenant='OTHER')
        db.execute("INSERT INTO leads(tenant,lead_id,name,status,updated_utc) VALUES('EXAMPLE','lead1','PRIVATE NAME','Won',?)",(now.isoformat(),))
        db.execute("INSERT INTO leads(tenant,lead_id,name,status,updated_utc) VALUES('OTHER','lead2','OTHER PRIVATE NAME','Open',?)",(now.isoformat(),))
    result=get_statistics(tenant='EXAMPLE',days=7,now=now)
    assert result['current']=={'inbound':3,'outbound':4,'sessions':2,'fallbacks':1,'errors':1,'handoffs':1,'contacts':1}
    assert result['previous']['inbound']==2
    assert len(result['daily'])==8
    assert sum(row['inbound'] for row in result['daily'])==3
    assert result['daily'][-1]['inbound']==0
    assert result['pipeline']['Won']==1 and result['pipeline']['Open']==0
    assert 'PRIVATE' not in json.dumps(result)
    whatsapp=get_statistics(tenant='EXAMPLE',days=7,channel='whatsapp',now=now)
    assert whatsapp['current']['inbound']==1 and whatsapp['current']['sessions']==1
    assert whatsapp['current']['errors']==0
    assert whatsapp['pipeline']==result['pipeline']
    assert [row['channel'] for row in whatsapp['channels']]==['whatsapp']


def test_statistics_empty_and_ninety_day_series(app):
    result=get_statistics(tenant='EMPTY',days=90)
    assert len(result['daily'])==91
    assert all(value==0 for value in result['current'].values())
    assert not result['intents'] and not result['errors']


def test_statistics_route_enforces_company_boundary(client):
    assert client.get('/admin/api/statistics').status_code==401
    with client.session_transaction() as state:
        set_test_identity(client,state,{'id':'owner','roles':['business_owner'],'tenant':'EXAMPLE'})
    assert client.get('/admin/api/statistics?tenant=OTHER').status_code==403
    own=client.get('/admin/api/statistics?tenant=EXAMPLE&days=7&channel=web')
    assert own.status_code==200 and own.json['tenant']=='EXAMPLE'
    assert own.headers['Cache-Control']=='no-store'
    assert 'leads' not in own.json


@pytest.mark.parametrize('query',['days=0','days=-1','days=366','days=no','channel=unknown',"channel=web%27%20OR%201=1"])
def test_statistics_rejects_bad_filters(client,query):
    with client.session_transaction() as state:
        set_test_identity(client,state,{'id':'owner','roles':['business_owner'],'tenant':'EXAMPLE'})
    assert client.get('/admin/api/statistics?'+query).status_code==400
