"""Shared presentation routes; existing API authentication remains authoritative."""
import json
from pathlib import Path

CONFIG=json.loads(Path(__file__).with_suffix('.json').read_text(encoding='utf-8'))
WORKSPACES={row['id']:row for row in [*CONFIG['workspaces'],CONFIG['platform']]}
ALIASES=CONFIG['aliases']


def legacy_location(section):
    if section=='platform':
        return {'workspace':'platform','view':'overview'}
    if section in ALIASES:
        return dict(ALIASES[section])
    for workspace in CONFIG['workspaces']:
        for view in workspace['views']:
            if view['section']==section:
                return {'workspace':workspace['id'],'view':view['id']}
    if section=='application':
        return {'workspace':'home','view':'application'}
    return {'workspace':'home','view':'overview'}


def effective_section(workspace,view=''):
    if workspace=='home' and view=='application':
        return 'application'
    definition=WORKSPACES.get(workspace)
    if not definition:
        raise ValueError('invalid_console_workspace')
    selected=next((row for row in definition['views'] if row['id']==view),None) if view else definition['views'][0]
    if selected is None:
        raise ValueError('invalid_console_view')
    return selected['section']
