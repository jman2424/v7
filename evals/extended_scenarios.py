"""Independent phrasings and follow-ups over the same public fictional facts.

Reference replay exercises validation only. Live runs measure the actual model.
"""
from evals.scenarios import agent, reply

PRICE_QUESTIONS = [
    'How much is the Trail Bottle?', 'What does a Trail Bottle cost?',
    'Please tell me the price of Trail Bottle.', 'Price check: Trail Bottle.',
    'Can you quote the listed Trail Bottle price?', 'What would I pay for one Trail Bottle?',
    'Is the Trail Bottle twenty pounds?', 'Tell me what Trail Bottle is priced at.',
    'I am looking at Trail Bottle. What is its price?', 'What is the current listed cost of Trail Bottle?',
    'Trail Bottle — how much?', 'How expensive is Trail Bottle?',
    'Before I decide, how much does Trail Bottle cost?', 'Could you show the price for Trail Bottle?',
    'I need the advertised price of Trail Bottle.', 'What price is shown for the Trail Bottle?',
    'Please help me find Trail Bottle pricing.', 'Give me the Trail Bottle price, please.',
    'What does your catalogue say Trail Bottle costs?', 'Tell me about the cost of the Trail Bottle.',
]
COMPARE_QUESTIONS = [
    'Compare Trail Bottle and Summit Bottle.', 'What differs between your two bottles?',
    'How do Trail and Summit compare?', 'Can you compare the bottle options?',
    'Tell me the differences between Trail Bottle and Summit Bottle.',
    'What are the capacities and prices of both bottles?', 'Which bottle is smaller and what do they cost?',
    'Show me Trail Bottle alongside Summit Bottle.', 'What should I know when comparing your bottles?',
    'Please explain the two bottle choices.', 'Give me a side-by-side bottle comparison.',
    'How does Summit Bottle differ from Trail Bottle?', 'I am choosing between Trail and Summit.',
    'Help me compare the size and price of your bottles.', 'Explain both bottle options to me.',
    'What does each of your bottles hold and cost?', 'Could you contrast the two bottle models?',
    'What are the main differences between the bottles you sell?',
    'Show the listed features of Trail and Summit.', 'Summit versus Trail: what changes?',
]
UNRELATED = [
    'Write me a Python calculator.', 'Make me a Python script.', 'Create a JavaScript calculator.',
    'Build a TypeScript calculator.', 'Generate a Python hello world.', 'Debug my Python homework.',
    'Write my essay.', 'Create a poem.', 'Solve my homework.', 'Write a SQL query for me.',
    'Help me with a Python calculator.', 'Can you write a JavaScript hello world?',
    'Please make a calculator in Python.', 'Build me an unrelated JavaScript app.',
    'Write a poem for school.', 'Generate my homework answers.',
    'Help me create a TypeScript calculator.', 'Can you solve this homework?',
    'Please write me an essay.', 'Make a Python hello world statement.',
]
EXTENDED_SCENARIOS = []
for index, question in enumerate(PRICE_QUESTIONS):
    EXTENDED_SCENARIOS.append({'id': f'price_paraphrase_{index:02}', 'business':'retail',
        'description':'Listed price, contextual follow-up and approved destination.', 'turns':[
            {'user':question, 'expect':{'answer_contains_all':['20'], 'answer_excludes':['£0']},
             'reference':reply('Trail Bottle costs £20.', ['product:trail'], state=agent('price', offerings=['product:trail']))},
            {'user':'How much does that one hold?', 'expect':{'answer_contains_any':['500']},
             'reference':reply('Trail Bottle holds 500 ml.', ['product:trail'], state=agent(offerings=['product:trail']))},
            {'user':'Where can I buy the Trail Bottle?', 'expect':{'navigation_contains':['trail-checkout'], 'requested_action':None},
             'reference':reply('Use the Buy Trail Bottle button to continue on the shop website.', ['product:trail'],
                state=agent('checkout','convert','open_destination',offerings=['product:trail']), navigation=['trail-checkout'])},
        ]})
for index, question in enumerate(COMPARE_QUESTIONS):
    EXTENDED_SCENARIOS.append({'id':f'compare_paraphrase_{index:02}', 'business':'retail',
        'description':'Compare, contextual feature question and uncertain inventory.', 'turns':[
            {'user':question, 'expect':{'answer_contains_all':['Trail','Summit']},
             'reference':reply('Trail Bottle holds 500 ml and costs £20. Summit Bottle holds 1000 ml and costs £35.',
                ['product:trail','product:summit'],state=agent('compare','recommend','compare_options',offerings=['product:trail','product:summit']))},
            {'user':'Which one holds more?', 'expect':{'answer_contains_any':['Summit','1000']},
             'reference':reply('Summit Bottle holds more: 1000 ml, compared with Trail Bottle at 500 ml.',
                ['product:trail','product:summit'],state=agent('compare',offerings=['product:trail','product:summit']))},
            {'user':'Can you promise ten are available today?', 'expect':{'answer_contains_any':['confirm','not connected','cannot guarantee',"can't guarantee"], 'requested_action':None},
             'reference':reply('Live stock is not connected. The team must confirm availability.', ['policy:stock'])},
        ]})
for index, task in enumerate(UNRELATED):
    term, meaning = f'colour {index}', f'preference {index}'
    EXTENDED_SCENARIOS.append({'id':f'memory_scope_{index:02}', 'business':'retail',
        'description':'Customer definition survives an unrelated request without becoming business policy.', 'turns':[
            {'user':f'{term} means {meaning}', 'expect':{'answer_contains_all':[term,meaning]},
             'reference':reply(f'Got it: {term} means {meaning}.',[],kind='conversation')},
            {'user':task,'expect':{'requested_action':None,'navigation_ids':[], 'answer_excludes':['```']},
             'reference':reply("I can help with this business, but I can't carry out unrelated tasks.",[],kind='conversation')},
            {'user':f'What does {term} mean?', 'expect':{'answer_contains_all':[meaning]},
             'reference':reply(f'You said {term} means {meaning}.',[],kind='conversation')},
        ]})
