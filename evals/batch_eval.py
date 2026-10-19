"""Run the extended quality matrix in supervised batches with a total spend cap."""
import argparse
from decimal import Decimal
import json
from pathlib import Path
import subprocess
import sys
import time

from evals.agent_eval import Settings, selected_scenarios


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', required=True)
    parser.add_argument('--env-file', required=True)
    parser.add_argument('--model', default='gpt-6-sol')
    parser.add_argument('--max-total-usd', default='1.50')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    budget = Decimal(args.max_total_usd)
    if not budget.is_finite() or not Decimal('0') < budget <= Decimal('5'):
        parser.error('Total budget must be between zero and five dollars.')
    Settings(live=True, extended=True, model=args.model).validate()
    args.output.mkdir(parents=True, exist_ok=False)
    scenarios = selected_scenarios(Settings(extended=True))
    results, cost, started = [], Decimal('0'), time.monotonic()
    for offset in range(0, len(scenarios), 6):
        remaining = budget - cost
        if remaining <= 0 or time.monotonic() - started > 1200:
            break
        path = args.output / f'batch-{offset//6:02}.json'
        command = [sys.executable, '-m', 'evals.agent_eval', '--live', '--extended',
            '--env-file', args.env_file, '--model', args.model, '--max-requests','20',
            '--max-budget-usd', str(min(remaining, Decimal('0.50'))), '--max-seconds','180', '--output',str(path)]
        for scenario in scenarios[offset:offset+6]:
            command += ['--scenario', scenario['id']]
        child = subprocess.run(command, capture_output=True, text=True, timeout=240)
        if not path.exists():
            results.append({'status':'worker_failed', 'exit_code':child.returncode})
            break
        report = json.loads(path.read_text(encoding='utf-8'))
        usage = report.get('usage', {})
        cost += Decimal(str(usage.get('known_cost_usd', 0))) + Decimal(str(usage.get('unknown_cost_ceiling_usd', 0)))
        row = {key:report.get(key) for key in ('status','revision','working_tree_dirty','runtime_code_sha256',
            'scenarios_planned','scenarios_passed','turns_planned','turns_executed','turns_passed')}
        row['report'] = str(path)
        results.append(row)
        print(json.dumps({'batch':offset//6, **row, 'cumulative_cost_ceiling_usd':str(cost)}), flush=True)
        if usage.get('unknown_cost_requests') or report.get('stop_reason'):
            break
    planned = sum(len(scenario['turns']) for scenario in scenarios)
    complete = sum(row.get('scenarios_planned',0) for row in results) == len(scenarios)
    summary = {'status':'passed' if complete and all(row['status']=='passed' for row in results) else 'failed_or_incomplete',
        'scenarios_planned':len(scenarios), 'turns_planned':planned,
        'turns_executed':sum(row.get('turns_executed',0) for row in results),
        'turns_passed':sum(row.get('turns_passed',0) for row in results),
        'cost_ceiling_usd':str(cost), 'max_total_usd':str(budget), 'batches':results}
    (args.output/'summary.json').write_text(json.dumps(summary,indent=2), encoding='utf-8')
    print(json.dumps({key:value for key,value in summary.items() if key!='batches'}))
    return 0 if summary['status']=='passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
