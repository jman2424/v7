"""Live platform policy is public, current and scoped to the marketing tenant."""
import json
from dataclasses import replace
from types import SimpleNamespace

from service import platform_offer_knowledge, referrals, subscriptions


def test_personal_advice_is_not_replaced_by_the_tariff_shortcut():
    for question in ['Compare your plans and recommend one for my business.',
                     'What plan should I choose based on price and features?',
                     'Help me choose between Starter and Business pricing plans.',
                     'Which pricing plan is best for my limited budget?']:
        assert platform_offer_knowledge.automatic_plan_answer(question, {'enabled': True}) is None


def test_plan_reasoning_uses_current_enforced_entitlements_without_legacy_quotas(monkeypatch):
    monkeypatch.setattr(subscriptions, 'internal_business', lambda tenant: tenant == 'MARKETING')
    assert platform_offer_knowledge.public_plan_context('OTHER') is None
    context = platform_offer_knowledge.public_plan_context('MARKETING')
    from service.plan_catalog import public_plans
    for actual, expected in zip(context['plans'], public_plans()):
        assert actual['locations'] == expected['locations']
        assert actual['staff_accounts'] == expected['staff_accounts']
        assert actual['analytics'] == expected['analytics']
    assert 'website_conversations' not in json.dumps(context)
    assert 'whatsapp_messages' not in json.dumps(context)
    assert 'separately prepaid' in context['usage'] and 'separate costs' in context['whatsapp']
    from service.grounded_money import monetary_claims_supported
    evidence = [{'name': 'Fictional platform', 'subscription_plans': context}]
    # Limits are not a bag of price amounts. Prices keep their own catalogue
    # sources and protected commercial terms.
    assert not monetary_claims_supported('Starter costs GBP 99 per month plus GBP 149 setup.', evidence)
    assert not monetary_claims_supported('Scale costs GBP 99 per month.', evidence)


def test_platform_plan_comparison_uses_billing_catalogue_and_keeps_context(client, monkeypatch):
    monkeypatch.setattr(subscriptions, 'internal_business', lambda tenant: tenant == 'VERTEX')
    with client.application.app_context():
        knowledge = platform_offer_knowledge.public_knowledge('VERTEX')
        answer = platform_offer_knowledge.automatic_plan_answer('Compare Starter and Business pricing plans', knowledge)
        assert 'Starter: £99.00/month plus £149.00 one-time setup' in answer
        assert 'Business: £199.00/month plus £299.00 one-time setup' in answer
        assert '5 staff accounts' in answer and 'No AI credit is included' in answer
        assert 'available' not in answer and 'Scale:' not in answer
        followup = platform_offer_knowledge.automatic_plan_answer('Which one allows five staff?', knowledge,
            [{'role': 'user', 'content': 'Compare Starter and Business pricing plans'}])
        assert 'Business:' in followup and '5 staff accounts' in followup
        for question in ['green means good', 'how do I setup V7?', 'How do I setup my Business plan?', 'cancel my plan', 'how does referral pricing work?']:
            assert platform_offer_knowledge.automatic_plan_answer(question, knowledge) is None
        assert platform_offer_knowledge.automatic_plan_answer('What should staff do to install the widget?', knowledge,
            [{'role': 'user', 'content': 'Compare Starter and Business pricing plans'}]) is None
        assert platform_offer_knowledge.automatic_plan_answer('Which one allows five staff?', knowledge) is None
        assert platform_offer_knowledge.automatic_plan_answer('Compare Starter and Business pricing plans', None) is None


def test_platform_pricing_cannot_fall_into_retail_compare_or_model(client, monkeypatch):
    from handlers.handler_v7 import MessageHandlerV7
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.setattr(subscriptions, 'internal_business', lambda tenant: tenant == 'VERTEX')
    with client.application.app_context():
        handler = MessageHandlerV7(SimpleNamespace())
        handler.tenant_key = 'VERTEX'
        def unexpected(*args, **kwargs):
            raise AssertionError('Current platform plans should not depend on model availability')
        monkeypatch.setattr(handler, '_grounded_answer', unexpected)
        result = handler.handle('Compare Starter and Business pricing plans', SimpleNamespace(tenant='VERTEX', channel='web'), {})
        assert result['facts']['source'] == 'current_platform_plans'
        assert '£99.00/month' in result['reply'] and '£299.00 one-time setup' in result['reply']
        monkeypatch.setattr(client.application.container, 'settings',
            replace(client.application.container.settings, BASE_URL='https://example.com'))
        handler.website_destinations = [{'id': 'owner-pricing', 'label': 'Compare plans',
            'url': 'https://example.com/#pricing', 'purpose': 'Compare plans', 'enabled': True}]
        result = handler.handle('Compare Starter and Business pricing plans', SimpleNamespace(tenant='VERTEX', channel='web'), {})
        assert result['actions'][0]['url'] == 'https://example.com/#pricing'
        assert result['actions'][0]['label'] == 'Compare plans'
        handler.website_destinations[0]['enabled'] = False
        result = handler.handle('Compare Starter and Business pricing plans', SimpleNamespace(tenant='VERTEX', channel='web'), {})
        assert not result.get('actions')


def test_routine_plan_answers_do_not_volunteer_zero_vat_status(client, monkeypatch):
    monkeypatch.setattr(subscriptions, 'internal_business', lambda tenant: tenant == 'VERTEX')
    monkeypatch.setenv('V7_VAT_REGISTERED', 'false')
    with client.application.app_context():
        knowledge = platform_offer_knowledge.public_knowledge('VERTEX')
        for question in ['Compare Starter and Business pricing plans', 'How much does the Starter plan cost?']:
            answer = platform_offer_knowledge.automatic_plan_answer(question, knowledge)
            assert '£99.00/month' in answer
            assert 'VAT' not in answer
        asked = platform_offer_knowledge.automatic_plan_answer('Compare Starter and Business pricing including VAT', knowledge)
        assert 'No VAT is added to the published prices.' in asked
        assert 'not VAT-registered' not in asked
        monkeypatch.setenv('V7_VAT_REGISTERED', 'true')
        registered = platform_offer_knowledge.automatic_plan_answer('Compare Starter and Business pricing plans', knowledge)
        assert 'VAT is charged at 20%' in registered


def test_other_businesses_never_receive_platform_referral_rules(client,monkeypatch):
    monkeypatch.setattr(subscriptions,'internal_business',lambda tenant:tenant=='VERTEX')
    assert platform_offer_knowledge.public_knowledge('EXAMPLE') is None
    assert platform_offer_knowledge.public_destinations('EXAMPLE',[])==[]
    with client.application.app_context():
        knowledge=platform_offer_knowledge.public_knowledge('VERTEX')
    assert knowledge['joining_setup_percent']==100
    assert all(row['referred_setup']=='£0.00' for row in knowledge['prices'])
    assert knowledge['prices'][0]['referred_first_month']=='£59.40'
    encoded=json.dumps(knowledge)
    assert 'owner_hash' not in encoded and 'qualifying_invoice' not in encoded


def test_live_pause_and_saved_knowledge_fallback_reflect_current_terms(client,monkeypatch):
    monkeypatch.setattr(subscriptions,'internal_business',lambda tenant:True)
    with client.application.app_context():
        knowledge=platform_offer_knowledge.public_knowledge('VERTEX')
        text=platform_offer_knowledge.automatic_offer_answer('How does your referral work?',knowledge)
        assert 'no setup fee (£0)' in text and '40%' in text
        referrals.set_program('VERTEX',False,'')
        knowledge=platform_offer_knowledge.public_knowledge('VERTEX')
        assert 'paused' in platform_offer_knowledge.automatic_offer_answer('referrals',knowledge)
        assert platform_offer_knowledge.automatic_offer_answer('Do you deliver lamps?',knowledge) is None


def test_automatic_referral_policy_not_catalogue_shortcut(client,monkeypatch):
    from handlers.handler_v7 import MessageHandlerV7
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    handler=MessageHandlerV7(SimpleNamespace())
    monkeypatch.setattr(handler,'_grounded_answer',lambda *args,**kwargs:None)
    monkeypatch.setattr(platform_offer_knowledge,'public_knowledge',lambda tenant:{'enabled':1,'percent':40,'joining_setup_percent':100,'sponsor_setup_percent':40})
    reply=handler.handle('Tell me about referrals',SimpleNamespace(tenant='VERTEX',channel='web'),{})
    assert reply['intent']=='faq' and 'no setup fee (£0)' in reply['reply']


def test_contact_handoff_is_recorded_before_ai_prose(client,monkeypatch):
    from handlers.handler_v7 import MessageHandlerV7
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    handler=MessageHandlerV7(SimpleNamespace())
    def unexpected(*args,**kwargs):
        raise AssertionError('Handoff must not be intercepted by a model answer')
    monkeypatch.setattr(handler,'_grounded_answer',unexpected)
    reply=handler.handle('Talk to a human',SimpleNamespace(tenant='EXAMPLE',channel='web'),{})
    assert reply['intent']=='human_handoff'
    reply=handler.handle('contact@example.test',SimpleNamespace(tenant='EXAMPLE',channel='web'),{'sales_agent':{'stage':'handoff'}})
    assert reply['intent']=='handoff_contact_captured'
    assert reply['entities']['email']=='contact@example.test'


def test_platform_navigation_respects_disabled_owner_links(client,monkeypatch):
    monkeypatch.setattr(subscriptions,'internal_business',lambda tenant:True)
    with client.application.app_context():
        monkeypatch.setattr(client.application.container,'settings',replace(client.application.container.settings,BASE_URL='https://example.com'))
        configured=[{'id':'platform_referrals','url':'https://example.com/console/account#business-referrals','enabled':False}]
        destinations=platform_offer_knowledge.public_destinations('VERTEX',configured)
    assert not any(row['id']=='platform_referrals' for row in destinations)
    assert any(row['id']=='platform_plan_starter' for row in destinations)


def test_handler_passes_public_playbook_and_preserves_verified_task_state(monkeypatch):
    from handlers.handler_v7 import MessageHandlerV7
    from service import grounded_conversation
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    handler=MessageHandlerV7(SimpleNamespace(rewriter=SimpleNamespace(_client=object(),_model='test-model')))
    seen={}
    def answer(*args,**kwargs):
        seen.update(kwargs['agent_context'])
        kwargs['agent_state'].update({'_validated_grounded':True,'stage':'convert','next_action':'open_destination'})
        return 'Open the selected service to review your next step.'
    monkeypatch.setattr(grounded_conversation,'answer',answer)
    previous={'selected_offering_id':'product:starter','requirements':['one location']}
    response=handler._grounded_answer('Choose that one',{'sales_agent':previous})
    assert seen['previous_agent']==previous
    assert seen['playbook']['primary_goal']==handler.sales_playbook['primary_goal']
    assert response['agent']['stage']=='convert'


def test_selected_product_beyond_catalogue_preview_remains_available(monkeypatch):
    from handlers.handler_v7 import MessageHandlerV7
    from retrieval.catalog_store import CatalogStore
    from service import grounded_conversation
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    catalog=CatalogStore(catalog={'categories':[{'id':'services','name':'Services','items':[
        {'sku':f'package-{index}','name':f'Package {index}','price':index+1} for index in range(70)
    ]}]})
    handler=MessageHandlerV7(SimpleNamespace(catalog=catalog,rewriter=SimpleNamespace(_client=object(),_model='test-model')))
    seen=[]
    monkeypatch.setattr(grounded_conversation,'answer',lambda *args,**kwargs:seen.append(args[3]))
    handler._grounded_answer('How do I get started?',{'sales_agent':{'selected_offering_id':'product:package-69','offering_ids':['product:package-69']}})
    assert seen[0]['product:package-69']['price']==70


def test_subscription_report_previews_free_setup_without_spending(client,monkeypatch):
    from tests.test_referrals import welcome
    welcome(monkeypatch)
    assert subscriptions.report('EXAMPLE',include_api=False)['referral_setup_percent']==100
    assert referrals.reserve('EXAMPLE','implementation','first_setup')['percent']==100
