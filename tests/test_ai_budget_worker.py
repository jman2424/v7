"""Durable notification retries and accounting never send real emails."""
import time
from service import ai_budget as budget, ai_budget_store as store, ai_budget_worker as worker
from service.account_service import AccountService
from tests import test_ai_budget_payments
from tests.test_ai_budget_payments import reserve, process

card=test_ai_budget_payments.card


def test_notification_claim_retry_and_opt_out(client,card,monkeypatch):
    container=client.application.container
    sent=[]
    monkeypatch.setattr(AccountService,'list_accounts',lambda self,tenant:[{'email':'owner@example.test','roles':['business_owner'],'active':True}])
    def send(*args,**kwargs):
        sent.append((args,kwargs))
        if len(sent)==1:
            raise ValueError('PRIVATE transport body')
    monkeypatch.setattr(worker.registration_mail,'send_transactional',send)
    budget.save_preferences('EXAMPLE',{'email_alerts':True},'owner')
    with store.connection('EXAMPLE',write=True) as db:
        store.notify(db,'EXAMPLE','low_balance','one',{},email=True)
    with client.application.app_context():
        assert worker.notify_one(container,'EXAMPLE')
        assert not worker.notify_one(container,'EXAMPLE')
    with store.connection('EXAMPLE',write=True) as db:
        db.execute('UPDATE ai_budget_notifications SET available=0 WHERE tenant=?',('EXAMPLE',))
    with client.application.app_context():
        assert worker.notify_one(container,'EXAMPLE')
        assert not worker.notify_one(container,'EXAMPLE')
    assert len(sent)==2 and sent[0][1]['idempotency_key']==sent[1][1]['idempotency_key']
    assert '/console/budget?tenant=EXAMPLE' in sent[1][0][2]
    assert 'PRIVATE' not in str(sent)
    with store.connection('EXAMPLE',write=True) as db:
        store.notify(db,'EXAMPLE','low_balance','two',{},email=True)
    budget.save_preferences('EXAMPLE',{'email_alerts':False},'owner')
    with client.application.app_context():
        worker.notify_one(container,'EXAMPLE')
    assert len(sent)==2


def test_uncertain_mail_does_not_resend_after_idempotency_retention(client,card,monkeypatch):
    sent=[]
    monkeypatch.setattr(worker.registration_mail,'send_transactional',lambda *args,**kwargs:sent.append(1))
    with store.connection('EXAMPLE',write=True) as db:
        store.notify(db,'EXAMPLE','recharge_succeeded','stale',{},email=True)
        db.execute("UPDATE ai_budget_notifications SET state='sending',attempts=1,created=?,available=0 WHERE tenant=?",(time.time()-86400,'EXAMPLE'))
    with client.application.app_context():
        assert worker.notify_one(client.application.container,'EXAMPLE')
    assert not sent
    with store.connection('EXAMPLE') as db:
        assert db.execute('SELECT state FROM ai_budget_notifications WHERE tenant=?',('EXAMPLE',)).fetchone()['state']=='needs_review'


def test_verified_fee_is_platform_bookkeeping_not_a_balance_deduction(client,card):
    ref=reserve(client)
    process(client,ref)
    charge=next(o for p,o in card['objects'].items() if p.startswith('/v1/charges/'))
    charge['balance_transaction']='txn_budget'
    card['objects']['/v1/balance_transactions/txn_budget']={'id':'txn_budget','source':charge['id'],'currency':'gbp','amount':500,'fee':28,'net':472,
        'fee_details':[{'type':'stripe_fee','amount':28,'currency':'gbp','description':'PRIVATE'}]}
    with client.application.app_context():
        assert worker.capture_payment_cost('EXAMPLE')
        assert not worker.capture_payment_cost('EXAMPLE')
    with store.connection('EXAMPLE') as db:
        cost=dict(db.execute('SELECT * FROM ai_budget_payment_costs WHERE tenant=?',('EXAMPLE',)).fetchone())
    assert cost['fee_pence']==28 and 'PRIVATE' not in cost['fee_details']
    assert budget.customer_report('EXAMPLE')['balance_pence']==500


def test_notification_template_escapes_tenant_and_contains_no_payment_action():
    subject,text,html=worker.render('payment_failed','https://example.test','A&B')
    assert 'tenant=A%26B' in text
    assert 'payment_failed' not in subject and '<script>' not in html
    assert 'card details' in text and 'Automatic recharge is paused' in text


def test_one_unavailable_tenant_cannot_stop_other_budget_work(client,monkeypatch):
    seen=[]
    def report(tenant,**kwargs):
        if tenant=='BROKEN':
            raise RuntimeError('synthetic_database_failure')
    monkeypatch.setattr(worker.usage_wallet,'report',report)
    monkeypatch.setattr(worker.payments,'reserve_recharge',lambda tenant:None)
    monkeypatch.setattr(worker,'notify_one',lambda container,tenant:seen.append(tenant) or False)
    monkeypatch.setattr(worker.subscriptions,'configured',lambda:False)
    with client.application.app_context():
        worker.run_once(client.application.container,tenants=['BROKEN','EXAMPLE'])
    assert 'EXAMPLE' in seen
