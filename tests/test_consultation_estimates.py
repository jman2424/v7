from service.reply_formatting import consultation_estimate
from tests.test_grounded_statements import run
from tests.test_grounded_conversation import _state


def test_starting_price_is_clearly_an_estimate_without_changing_amount_or_condition():
    text='Ceramic coating starting price: £400. Final quote on inspection.'
    result=consultation_estimate(text)
    assert text in result and 'This is an estimate, not a final quote.' in result
    assert consultation_estimate(result)==result
    assert consultation_estimate('Fixed monthly price: £99.')=='Fixed monthly price: £99.'


def test_live_api_stores_the_same_estimate_notice_the_customer_reads(app,client,monkeypatch):
    wrapper=app.container.for_tenant('EXAMPLE').handler
    monkeypatch.setattr(wrapper.h_v7,'handle',lambda *args,**kwargs:{
        'reply':'Coating starting price: £400. Final quote on inspection.', 'intent':'price_check','facts':{}})
    response=client.post('/chat_api',json={'tenant':'EXAMPLE','message':'What is the starting price?'})
    assert response.status_code==200 and 'This is an estimate, not a final quote.' in response.json['reply']
    history=wrapper.memory.get(response.json['session_id'],'conversation_history')
    assert history[-1]['content']==response.json['reply']


def test_consultation_form_explains_assessments_are_estimates(monkeypatch):
    answer,state,_,_=run(monkeypatch,{'business':{'name':'Fixture'}},
        question='Open a consultation form.',text='Open the consultation request form.',
        sources=['capability:request:consultation'],ids=['capability:request:consultation:answer'],
        allowed_actions=['consultation'],requested_action='consultation',
        agent=_state('book',action='open_request_form'))
    assert 'estimate, not a final quote' in answer
    assert state['requested_action']=='consultation'
