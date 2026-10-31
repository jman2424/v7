"""Optional execution policy over existing services; never an intelligence gate.

No permission decision is cached or taken from model/customer arguments. Missing
policy preserves explicitly inventoried legacy services until operator migration.
New registry entries default to disabled for unmigrated businesses.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
import sqlite3

from service.business_management import revision

FILENAME = 'agent_modules.json'
PLANS = frozenset({'starter', 'business', 'scale'})


@dataclass(frozen=True)
class Module:
    label: str
    tools: tuple[str, ...]
    channels: tuple[str, ...]
    approval: str
    legacy: bool = False


REGISTRY = {
    'consultation': Module('Appointment requests', ('request_consultation',), ('web', 'owner'), 'customer_confirmation', True),
    'quote': Module('Quote requests', ('request_quote',), ('web', 'owner'), 'customer_confirmation', True),
    'callback': Module('Callback requests', ('request_callback',), ('web', 'owner'), 'customer_confirmation', True),
    'booking_management': Module('Manage native appointments', ('reschedule_appointment', 'cancel_appointment'), ('receipt',), 'verified_receipt_and_confirmation', True),
    'email': Module('Support email', ('draft_email', 'send_approved_email'), ('email',), 'owner_review_or_verified_routine', True),
    'phone': Module('Business calls', ('take_call_message', 'answer_routine_call'), ('phone',), 'configured_mode_and_verified_reply', True),
}


def boolean_map(value):
    if (not isinstance(value, dict) or set(value) != set(REGISTRY)
            or any(type(enabled) is not bool for enabled in value.values())):
        raise ValueError('invalid_module_settings')
    return value.copy()


def validate(value):
    if (not isinstance(value, dict) or set(value) != {'version', 'modules'}
            or type(value['version']) is not int or value['version'] != 1
            or not isinstance(value['modules'], dict) or set(value['modules']) - set(REGISTRY)):
        raise ValueError('invalid_module_configuration')
    for row in value['modules'].values():
        if (not isinstance(row, dict) or set(row) != {'granted', 'enabled'}
                or type(row['granted']) is not bool or type(row['enabled']) is not bool):
            raise ValueError('invalid_module_configuration')
    # Older policies do not grant a newly added module; extending the registry
    # must not invalidate or disable their other existing explicit permissions.
    return {'version': 1, 'modules': {key: value['modules'].get(key, {'granted': False, 'enabled': False}).copy()
                                    for key in REGISTRY}}


def document(storage, tenant):
    try:
        return storage.read_json(tenant, FILENAME)
    except FileNotFoundError:
        return None


def platform_policy():
    """Deployment-owned restrictions; no tenant can override the global policy."""
    raw = os.getenv('V7_AGENT_MODULE_POLICY_JSON', '{}')
    if len(raw) > 8192:
        raise ValueError('invalid_platform_module_policy')
    value = json.loads(raw)
    if (not isinstance(value, dict) or set(value) - {'disabled', 'plans'}
            or not isinstance(value.get('disabled', []), list)
            or any(not isinstance(key, str) or key not in REGISTRY for key in value.get('disabled', []))
            or not isinstance(value.get('plans', {}), dict) or set(value.get('plans', {})) - set(REGISTRY)):
        raise ValueError('invalid_platform_module_policy')
    plans = {}
    for key, allowed in value.get('plans', {}).items():
        if (not isinstance(allowed, list)
                or any(not isinstance(plan, str) or plan not in PLANS for plan in allowed)):
            raise ValueError('invalid_platform_module_policy')
        plans[key] = frozenset(allowed)
    return frozenset(value.get('disabled', [])), plans


def decisions(storage, tenant, names):
    """Policy only. Existing actor, channel, consent and integration gates remain."""
    names = tuple(names)
    if any(not isinstance(name, str) or name not in REGISTRY for name in names):
        raise ValueError('unknown_module')
    try:
        raw = document(storage, tenant)
        config = validate(raw) if raw is not None else None
        disabled, plans = platform_policy()
        restricted = any(plans.get(name, PLANS) != PLANS for name in names)
        plan = None
        if restricted:
            from service.subscriptions import configured_plan
            current = configured_plan(tenant)
            plan = current.get('id') if isinstance(current, dict) else None
        result = {}
        for name in names:
            row = config['modules'][name] if config else {'granted': REGISTRY[name].legacy, 'enabled': REGISTRY[name].legacy}
            reason = ('platform_disabled' if name in disabled else
                      'plan_not_allowed' if plans.get(name, PLANS) != PLANS and plan not in plans[name] else
                      'not_granted' if not row['granted'] else
                      'owner_disabled' if not row['enabled'] else '')
            result[name] = {'allowed': not reason, 'reason': reason, 'managed': config is not None}
        return result
    except (OSError, RuntimeError, sqlite3.Error, ValueError, TypeError, RecursionError) as exc:
        from service.chat_diagnostics import emit
        emit('chat_optional_failure', phase='module_policy', error_type=type(exc).__name__)
        return {name: {'allowed': False, 'reason': 'module_policy_unavailable', 'managed': True} for name in names}


def allowed(storage, tenant, name):
    return decisions(storage, tenant, (name,))[name]['allowed']


def effective_actions(storage, tenant, config=None):
    from service.conversion_actions import load_actions
    value = load_actions(storage, tenant) if config is None else config
    state = decisions(storage, tenant, ('consultation', 'quote', 'callback', 'booking_management'))
    result = {name: row.copy() for name, row in value.items()}
    for name in ('consultation', 'quote', 'callback'):
        if name in result and not state[name]['allowed']:
            result[name]['enabled'] = False
    if 'consultation' in result and not state['booking_management']['allowed']:
        result['consultation']['manage_bookings'] = False
    return result


def legacy_switches(storage, tenant):
    from service.conversion_actions import load_actions
    from service.business_channels import settings, grants
    actions = load_actions(storage, tenant)
    prefs, channel_grants = settings(storage, tenant), grants(storage, tenant)
    enabled = {name: actions[name]['enabled'] for name in ('consultation', 'quote', 'callback')}
    enabled['booking_management'] = actions['consultation'].get('manage_bookings', False)
    enabled.update({name: prefs[name]['enabled'] and channel_grants[name] for name in ('email', 'phone')})
    return enabled


def snapshot(container, tenant):
    raw = document(container.storage, tenant)
    config = validate(raw) if raw is not None else None
    legacy = legacy_switches(container.storage, tenant)
    policy = decisions(container.storage, tenant, REGISTRY)
    from service.business_channels import readiness
    channels = readiness(container, tenant)
    from service.tenant_access import activation
    active = activation(tenant)['active']
    rows = []
    for name, descriptor in REGISTRY.items():
        stored = config['modules'][name] if config else {'granted': legacy.get(name, False), 'enabled': legacy.get(name, False)}
        ready = legacy.get(name, False)
        if name in {'email', 'phone'}:
            ready = ready and channels['channels'][name]['configured'] and channels['worker_enabled']
        reason = policy[name]['reason'] or ('business_inactive' if not active else '' if ready else 'service_setup_required')
        rows.append({'id': name, 'label': descriptor.label, 'tools': list(descriptor.tools),
                     'channels': list(descriptor.channels), 'approval': descriptor.approval,
                     **stored, 'available': not reason, 'blocked_by': reason})
    return {'modules': rows, 'revision': revision(raw), 'initialized': config is not None,
            'core_intelligence_always_on': True, 'global_control': 'deployment_configuration'}


def update_grants(storage, tenant, value):
    grants = boolean_map(value)
    raw = document(storage, tenant)
    if raw is not None:
        config = validate(raw)
    else:
        legacy = legacy_switches(storage, tenant)
        config = {'version': 1, 'modules': {name: {'granted': False, 'enabled': legacy.get(name, False)}
                                         for name in REGISTRY}}
    for name, granted in grants.items():
        config['modules'][name]['granted'] = granted
    return config


def update_enabled(storage, tenant, value):
    enabled = boolean_map(value)
    raw = document(storage, tenant)
    if raw is None:
        raise ValueError('module_policy_not_initialized')
    config = validate(raw)
    if any(active and not config['modules'][name]['granted'] for name, active in enabled.items()):
        raise PermissionError('module_not_granted')
    for name, active in enabled.items():
        config['modules'][name]['enabled'] = active
    return config
