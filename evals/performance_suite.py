"""Repeatable fifty-conversation, content-safe provider benchmark.

Uses fictional fixtures and the existing accounted, no-retry evaluation runner.
Each conversation is isolated; failures remain failures, never fallback successes.
This measures model/validation turns, not production HTTP/database latency.
"""
from __future__ import annotations

import argparse
import copy
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import statistics
import time


def scenarios():
    from evals.scenarios import SCENARIOS
    from evals.extended_scenarios import EXTENDED_SCENARIOS
    rows = copy.deepcopy(SCENARIOS)
    for prefix, count in [('price_paraphrase_', 10), ('compare_paraphrase_', 10), ('memory_scope_', 3)]:
        rows.extend(copy.deepcopy([r for r in EXTENDED_SCENARIOS if r['id'].startswith(prefix)][:count]))
    policy = next(r for r in SCENARIOS if r['id'] == 'retail_support_interruption')['turns'][1]
    price = next(r for r in EXTENDED_SCENARIOS if r['id'] == 'price_paraphrase_00')['turns'][0]
    compare = next(r for r in EXTENDED_SCENARIOS if r['id'] == 'compare_paraphrase_00')['turns'][0]
    casual = next(r for r in SCENARIOS if r['id'] == 'customer_scope_and_recall')['turns'][-1]
    questions = ['How do returns work?', 'What is your returns policy?', 'Can I return an unused bottle?',
                 'How long is the returns period?', 'Where can I read the return instructions?',
                 'Before buying, explain your policy on unused returns.', 'What should I do to return a bottle?',
                 'Tell me the conditions for returning unused bottles.', 'I need information about returns.',
                 'Explain the published return policy, please.']
    for index, question in enumerate(questions):
        turn = copy.deepcopy(policy)
        turn['user'] = question
        # These conversations start with policy, so there is no old shortlist.
        turn['expect'].pop('last_offering_ids', None)
        rows.append({'id': f'latency_policy_{index:02}', 'business': 'retail',
                     'description': 'Published policy followed by a catalogue question.',
                     'turns': [turn, copy.deepcopy(price)]})
    for index, question in enumerate(["How'd your day go?", 'How are you?', 'How is your day?',
                                      'How was your day?', 'How did your day go?']):
        turn = copy.deepcopy(casual)
        turn['user'] = question
        rows.append({'id': f'latency_greeting_{index:02}', 'business': 'retail',
                     'description': 'Small talk followed by a real business question.',
                     'turns': [turn, copy.deepcopy(price)]})
    for index in range(5):
        turn = copy.deepcopy(compare)
        turn['user'] = ('I am planning several walking trips and want to understand your published options. '
                        'I care about carrying a bottle comfortably and knowing its actual capacity. '
                        'Please use the information you have rather than guessing about stock or delivery. '
                        'Compare Trail Bottle and Summit Bottle, including their listed prices and capacities. '
                        + 'I would like the comparison to stay clear and concise. ' * (index + 3))
        rows.append({'id': f'latency_long_question_{index:02}', 'business': 'retail',
                     'description': 'Long customer question followed by a policy interruption.',
                     'turns': [turn, copy.deepcopy(policy)]})
        rows[-1]['turns'][-1]['expect'].pop('last_offering_ids', None)
    assert len(rows) == 50 and len({r['id'] for r in rows}) == 50
    return rows


def percentile(values, quantile):
    return sorted(values)[max(0, math.ceil(len(values) * quantile) - 1)] if values else None


def summarize(reports):
    calls = [call for report in reports for call in report['usage'].get('calls', [])]
    turns = [row for report in reports for row in report.get('results', [])]
    timings = [row['validation']['latency_ms'] for row in turns]
    model_timings = [row['validation']['latency_ms'] for row in turns if row['validation']['provider_completed']]
    provider_timings = [c['latency_ms'] for c in calls if 'latency_ms' in c]
    known = sum((Decimal(str(r['usage']['known_cost_usd'])) for r in reports), Decimal(0))
    unknown = sum((Decimal(str(r['usage']['unknown_cost_ceiling_usd'])) for r in reports), Decimal(0))
    return {'conversations_executed': sum(len({row['scenario_id'] for row in r.get('results', [])}) for r in reports),
            'conversations_passed': sum(r['scenarios_passed'] for r in reports),
            'turns_executed': len(turns), 'turns_passed': sum(r['passed'] for r in turns),
            'turn_p50_ms': statistics.median(timings) if timings else None,
            'turn_p95_ms': percentile(timings, .95),
            'model_backed_turn_p50_ms': statistics.median(model_timings) if model_timings else None,
            'model_backed_turn_p95_ms': percentile(model_timings, .95),
            'provider_p50_ms': statistics.median(provider_timings) if provider_timings else None,
            'provider_p95_ms': percentile(provider_timings, .95),
            'provider_calls': len(calls), 'input_tokens': sum(c.get('input_tokens') or 0 for c in calls),
            'output_tokens': sum(c.get('output_tokens') or 0 for c in calls),
            'cached_tokens': sum(c.get('cached_tokens') or 0 for c in calls),
            'known_cost_usd': str(known), 'unknown_cost_ceiling_usd': str(unknown),
            'failures': [{'scenario_id': r['scenario_id'], 'turn': r['turn'],
                          'failed_checks': [k for k, v in r['checks'].items() if not v],
                          'reason': r['validation'].get('rejection_reason')} for r in turns if not r['passed']]}


def run(*, target, env_file, output, max_budget_usd='0.65', model='gpt-4.1-mini', live=False, rich_business=False, http_pipeline=False):
    # The same trusted external harness can evaluate a frozen checkout. Insert
    # its root before importing runtime modules; never import credentials.
    import os
    import sys
    target = Path(target).resolve(strict=True)
    os.chdir(target)
    sys.path.insert(0, str(target))
    from evals import agent_eval
    runner = agent_eval.run_suite
    if http_pipeline:
        import importlib.util
        module_spec = importlib.util.spec_from_file_location('v7_http_performance', Path(__file__).with_name('http_performance.py'))
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        runner = module.run_suite
    if rich_business:
        # Deliberately oversized but public fictional knowledge, to exercise
        # the duplicate core/rule payload seen in real larger workspaces.
        for business in agent_eval.BUSINESSES.values():
            knowledge = business['knowledge']
            offerings = [copy.deepcopy(row) for key, row in knowledge.items() if key.startswith('offering:')]
            unit = ('Use the published care instructions for the item or service. '
                    'This care guide does not change the listed prices, returns policy or availability. '
                    'Ask the business team before using unlisted materials or methods on a special finish. ')
            rules = [{'id': f'care-{index}', 'title': f'Published care guidance {index}',
                      'description': f'Care guidance section {index}. ' + unit * 6,
                      'active': True, 'requires_manual_review': False} for index in range(8)]
            knowledge['business_core'] = {'industry': 'Synthetic benchmark business', 'offerings': offerings,
                                           'locations': [], 'business_rules': rules}
    rows = scenarios()
    agent_eval.SCENARIOS = rows
    fixture_hash = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
    ceiling = Decimal(max_budget_usd)
    if not Decimal(0) < ceiling <= Decimal('1.50'):
        raise ValueError('invalid_total_benchmark_budget')
    reports, started = [], time.monotonic()
    output = Path(output).resolve()

    def publish(report=None):
        active = reports + ([report] if report else [])
        document = {'schema_version': 1, 'model': model, 'mode': 'live' if live else 'reference_replay',
                    'measurement_scope': ('Full Flask/SQLite HTTP pipeline, excluding production DB/network/browser paint.'
                        if http_pipeline else 'Grounded model and deterministic validation; excludes production HTTP/DB overhead.'),
                    'context_profile': 'large_public_business' if rich_business else 'small_public_business',
                    'scenario_manifest_sha256': fixture_hash, 'scenario_ids': [r['id'] for r in rows],
                    'conversations_planned': 50, 'max_budget_usd': str(ceiling),
                    'elapsed_seconds': round(time.monotonic() - started, 3),
                    'summary': summarize(active), 'reports': active}
        temporary = output.with_suffix('.tmp')
        temporary.write_text(json.dumps(document, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
        temporary.replace(output)

    client = agent_eval.make_client(agent_eval.Settings(live=live, model=model, env_file=env_file))
    try:
        for group in ([rows] if http_pipeline else [[row] for row in rows]):
            totals = summarize(reports)
            remaining = ceiling - Decimal(totals['known_cost_usd']) - Decimal(totals['unknown_cost_ceiling_usd'])
            if remaining <= Decimal('0.002') or time.monotonic() - started > 1800:
                break
            settings_class = module.HttpSettings if http_pipeline else agent_eval.Settings
            settings = settings_class(live=live, model=model, env_file=env_file,
                scenario_ids=tuple(row['id'] for row in group), max_budget_usd=str(remaining),
                max_requests=300 if http_pipeline else 20, max_seconds=600 if http_pipeline else 120)
            report = runner(settings, emit=publish, client=client)
            reports.append(report)
            publish()
            print(json.dumps({'conversation': summarize(reports)['conversations_executed'],
                              'scenario': group[0]['id'], 'status': report['status'],
                              'known_cost_usd': summarize(reports)['known_cost_usd']}), flush=True)
            if report.get('stop_reason') or not report.get('accounting', {}).get('consistent'):
                break
    finally:
        if live:
            client.close()
    publish()
    return summarize(reports)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--env-file')
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--rich-business', action='store_true')
    parser.add_argument('--http-pipeline', action='store_true')
    parser.add_argument('--model', default='gpt-4.1-mini')
    parser.add_argument('--max-budget-usd', default='0.65')
    args = parser.parse_args()
    print(json.dumps(run(**vars(args))), flush=True)
