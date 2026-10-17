import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from service import grounded_conversation
from service.website_destinations import public_targets, validate
from routes.webchat_routes import _public_action_payload


def destination(**changes):
    return {'id':'starter','label':'Choose Starter','url':'https://shop.example/pricing#starter',
            'purpose':'When the customer wants to choose Starter.', 'enabled':True, **changes}


def test_destination_preserves_section_and_external_checkout():
    assert validate([destination()])[0]['url'].endswith('#starter')
    assert validate([destination(url='https://checkout.example/pay?plan=starter')])[0]['url'].endswith('?plan=starter')


@pytest.mark.parametrize('url',['javascript:alert(1)','http://shop.example/','https://localhost/',
                               'https://127.0.0.1/',
                               'https://' + ':'.join(('user', 'secret')) + '@' + 'shop.example/',
                               'https://shop.example/pay?api_key=secret'])
def test_unsafe_destinations_are_rejected(url):
    with pytest.raises(ValueError):
        validate([destination(url=url)])


def test_duplicates_and_disabled_links():
    with pytest.raises(ValueError):
        validate([destination(),destination()])
    assert public_targets(validate([destination(enabled=False)]),{},'https://shop.example/') == []
    disabled = destination(url='https://shop.example/products', enabled=False)
    assert public_targets(validate([disabled]),{'pages':[{'url':disabled['url'],'title':'Products'}]},
                          'https://shop.example/') == []


def test_imported_navigation_stays_on_tenant_website_and_excludes_private_routes():
    pages = [{'url':'https://shop.example/products','title':'Our products'},
             {'url':'https://other.example/products','title':'Other tenant'},
             {'url':'https://shop.example/console/account','title':'Account'}]
    targets = public_targets([],{'pages':pages},'https://shop.example/')
    assert len(targets) == 1 and targets[0]['label'] == 'Our products'


def test_public_payload_only_renders_safe_navigation():
    result = _public_action_payload({'actions':[{'type':'navigate','label':'Choose Starter',
                                               'url':'https://shop.example/pricing#starter'},
                                              {'type':'navigate','label':'Unsafe','url':'javascript:alert(1)'}]})
    assert len(result) == 1 and result[0]['url'].endswith('#starter')


def test_model_selects_known_ids_and_server_supplies_urls(monkeypatch):
    data = {'answer':'You can choose Starter below.', 'kind':'answer',
            'sources':['business'],'navigation':['starter']}
    def completion(*args,**kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(data)))])
    monkeypatch.setattr(grounded_conversation,'tracked_completion',completion)
    selected = []
    assert grounded_conversation.answer(Mock(),'gpt-4o-mini','Choose Starter',
        {'business':{'name':'Shop'}},[],'friendly',destinations=validate([destination()]),selected_links=selected)
    assert selected == [{'type':'navigate','label':'Choose Starter','url':'https://shop.example/pricing#starter'}]
    data['navigation'] = ['invented_checkout']
    assert grounded_conversation.answer(Mock(),'gpt-4o-mini','Choose Starter',
        {'business':{'name':'Shop'}},[],'friendly',destinations=validate([destination()])) is None


def test_deep_page_retrieval_finds_later_arabic_passage():
    from service.website_knowledge import relevant_passages
    knowledge = {'pages':[{'url':'https://shop.example/policy','title':'سياسة الشحن',
        'text':'معلومات عامة عن المتجر\n'*100 + 'الشحن الدولي متاح إلى البلدان المحددة في سياسة المتجر.'}]}
    passages = relevant_passages(knowledge,'هل الشحن الدولي متاح؟',limit=2)
    assert passages and any('الشحن الدولي متاح' in row['text'] for row in passages)


def test_operator_can_save_and_read_destination_configuration(client):
    from tests.conftest import set_test_identity
    with client.session_transaction() as state:
        set_test_identity(client,state,{'id':'operator','roles':['platform_admin'],'tenant':'EXAMPLE'})
    response = client.put('/admin/api/website-destinations?tenant=EXAMPLE',json=[destination()])
    assert response.status_code == 200
    saved = client.get('/admin/api/website-destinations?tenant=EXAMPLE')
    assert saved.status_code == 200
    assert saved.json['destinations'][0]['url'].endswith('#starter')


def test_staff_cannot_publish_navigation_targets(client):
    from tests.conftest import set_test_identity
    with client.session_transaction() as state:
        set_test_identity(client,state,{'id':'staff','roles':['business_staff'],'tenant':'EXAMPLE'})
    assert client.put('/admin/api/website-destinations?tenant=EXAMPLE',json=[destination()]).status_code == 403
