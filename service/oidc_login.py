"""Explicit provider links and browser-bound OpenID Connect login flows."""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import time
from urllib.parse import urlencode, urlsplit

from flask import current_app, session
import jwt
import requests

from service import session_store
from service.account_mfa import account_key

PROVIDERS = {'google': 'Google', 'microsoft': 'Microsoft'}
_OPAQUE = re.compile(r'[A-Za-z0-9_-]{43}\Z')
_GUID = re.compile(r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\Z')
_CONSUMER_TENANT = '9188040d-6c67-4c5b-b112-36a304b66dad'
_FLOW_SECONDS = 600
_COLUMNS = 'provider,configuration_hash,browser_hash,intent,verifier,nonce,tenant,identity,revision,session_hash,created,expires'


@dataclass(frozen=True)
class Provider:
    name: str
    client_id: str
    client_secret: str = field(repr=False)
    redirect_uri: str
    authority: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str

    def fingerprint(self):
        value = json.dumps([self.name, self.client_id, self.client_secret,
                            self.redirect_uri, self.authority], separators=(',', ':'))
        return hmac.new(str(current_app.secret_key).encode(), value.encode(), hashlib.sha256).hexdigest()


def _provider(name):
    if name not in PROVIDERS:
        raise ValueError('unknown_provider')
    prefix = 'V7_' + name.upper()
    client_id = os.getenv(prefix + '_CLIENT_ID', '').strip()
    client_secret = os.getenv(prefix + '_CLIENT_SECRET', '').strip()
    if not client_id or not client_secret or len(client_id) > 512 or len(client_secret) > 4096:
        return None
    settings = current_app.container.settings
    base = urlsplit(settings.BASE_URL)
    if (base.scheme not in {'http', 'https'} or not base.hostname or base.username or base.password
            or base.path not in {'', '/'} or base.query or base.fragment
            or (base.scheme == 'http' and (base.hostname not in {'localhost', '127.0.0.1', '::1'}
                or settings.ENVIRONMENT == 'production'))):
        return None
    # Derive the callback from configured server state, never request Host or a return URL.
    redirect_uri = f'{base.scheme}://{base.netloc}/auth/oidc/{name}/callback'
    if name == 'google':
        return Provider(name, client_id, client_secret, redirect_uri, '',
                        'https://accounts.google.com/o/oauth2/v2/auth',
                        'https://oauth2.googleapis.com/token',
                        'https://www.googleapis.com/oauth2/v3/certs')
    authority = os.getenv('V7_MICROSOFT_TENANT', 'common').strip().lower()
    if authority not in {'common', 'organizations', 'consumers'} and not _GUID.fullmatch(authority):
        return None
    endpoint = 'https://login.microsoftonline.com/' + authority
    return Provider(name, client_id, client_secret, redirect_uri, authority,
                    endpoint + '/oauth2/v2.0/authorize', endpoint + '/oauth2/v2.0/token',
                    endpoint + '/discovery/v2.0/keys')


def _database():
    return session_store.postgres_connection() if session_store._using_postgres() else session_store.connection()


def _execute(db, sql, params=()):
    return db.execute(sql.replace('?', '%s') if session_store._using_postgres() else sql, params)


def _tables(db):
    if session_store._using_postgres():
        return
    db.execute('CREATE TABLE IF NOT EXISTS oidc_states (state_hash TEXT PRIMARY KEY, provider TEXT NOT NULL, '
               'configuration_hash TEXT NOT NULL, browser_hash TEXT NOT NULL, intent TEXT NOT NULL, '
               'verifier TEXT NOT NULL, nonce TEXT NOT NULL, tenant TEXT NOT NULL, identity TEXT, revision TEXT, '
               'session_hash TEXT, created REAL NOT NULL, expires REAL NOT NULL)')
    db.execute('CREATE INDEX IF NOT EXISTS oidc_states_expires ON oidc_states(expires)')
    db.execute('CREATE TABLE IF NOT EXISTS oidc_links (provider TEXT NOT NULL, client_id TEXT NOT NULL, '
               'issuer TEXT NOT NULL, subject TEXT NOT NULL, account TEXT NOT NULL, identity TEXT NOT NULL, '
               'created REAL NOT NULL, PRIMARY KEY(provider,client_id,issuer,subject), UNIQUE(provider,client_id,account))')
    db.execute('CREATE INDEX IF NOT EXISTS oidc_links_account ON oidc_links(account)')


def _digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _reference(user):
    platform = bool({'platform_admin', 'admin'}.intersection(user['roles']))
    return {key: user[key] for key in ('id', 'email')} | {'tenant': None if platform else user['tenant']}


def providers_status(user=None):
    linked = set()
    if user is not None:
        with _database() as db:
            _tables(db)
            linked = {(row[0], row[1]) for row in _execute(db,
                      'SELECT provider,client_id FROM oidc_links WHERE account=?', (account_key(user),))}
    result = []
    for name, label in PROVIDERS.items():
        config = _provider(name)
        result.append({'id': name, 'name': label, 'configured': config is not None,
                       'linked': bool(config and (name, config.client_id) in linked),
                       'has_links': any(saved_provider == name for saved_provider, _ in linked)})
    return {'providers': result}


def start(name, data):
    from service.security import _revision, management_user
    config = _provider(name)
    if config is None:
        raise ValueError('provider_not_configured')
    if (not isinstance(data, dict) or not isinstance(data.get('intent'), str)
            or data.get('intent') not in {'login', 'link'}
            or any(key not in {'intent', 'tenant', 'csrf_token'} for key in data)
            or not isinstance(data.get('tenant', ''), str)):
        raise ValueError('invalid_oidc_request')
    intent = data['intent']
    user = management_user() if intent == 'link' else None
    if intent == 'login' and session.get('user'):
        raise ValueError('already_signed_in')
    storage = current_app.container.storage
    tenant = storage.canonical_tenant_key(data.get('tenant') or current_app.container.settings.BUSINESS_KEY)
    if not storage.tenant_exists(tenant):
        raise ValueError('unknown_tenant')
    reference = _reference(user) if user else None
    revision = _revision(user) if user else None
    browser = session.get('oidc_browser')
    if not isinstance(browser, str) or not _OPAQUE.fullmatch(browser):
        browser = secrets.token_urlsafe(32)
        session['oidc_browser'] = browser
    state, verifier, nonce = (secrets.token_urlsafe(32) for _ in range(3))
    now = time.time()
    with _database() as db:
        _tables(db)
        _execute(db, 'DELETE FROM oidc_states WHERE expires<=? OR browser_hash=?', (now, _digest(browser)))
        _execute(db, 'INSERT INTO oidc_states (state_hash,' + _COLUMNS + ') VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                 (_digest(state), name, config.fingerprint(), _digest(browser), intent, verifier, nonce, tenant,
                  json.dumps(reference, separators=(',', ':')) if reference else None, revision,
                  _digest(session['management_token']) if user else None, now, now + _FLOW_SECONDS))
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    params = {'client_id': config.client_id, 'response_type': 'code', 'redirect_uri': config.redirect_uri,
              'scope': 'openid email', 'state': state, 'nonce': nonce, 'code_challenge': challenge,
              'code_challenge_method': 'S256', 'prompt': 'select_account'}
    return {'authorization_url': config.authorization_endpoint + '?' + urlencode(params)}


def _consume_state(config, state):
    browser = session.get('oidc_browser')
    if (not isinstance(state, str) or not _OPAQUE.fullmatch(state)
            or not isinstance(browser, str) or not _OPAQUE.fullmatch(browser)):
        raise ValueError('invalid_oidc_state')
    with _database() as db:
        _tables(db)
        if not session_store._using_postgres():
            db.execute('BEGIN IMMEDIATE')
        lock = ' FOR UPDATE' if session_store._using_postgres() else ''
        row = _execute(db, 'SELECT ' + _COLUMNS + ' FROM oidc_states WHERE state_hash=?' + lock,
                       (_digest(state),)).fetchone()
        if not row:
            raise ValueError('invalid_oidc_state')
        flow = dict(zip(_COLUMNS.split(','), row))
        if (any(not isinstance(flow[key], str) for key in
                ('provider', 'configuration_hash', 'browser_hash', 'intent', 'verifier', 'nonce', 'tenant'))
                or not _OPAQUE.fullmatch(flow['verifier']) or not _OPAQUE.fullmatch(flow['nonce'])
                or flow['intent'] not in {'login', 'link'}
                or flow['provider'] != config.name or not hmac.compare_digest(flow['browser_hash'], _digest(browser))
                or not hmac.compare_digest(flow['configuration_hash'], config.fingerprint())
                or any(isinstance(flow[key], bool) or not isinstance(flow[key], (int, float))
                       or not math.isfinite(flow[key]) for key in ('created', 'expires'))
                or flow['expires'] <= time.time()):
            raise ValueError('invalid_oidc_state')
        _execute(db, 'DELETE FROM oidc_states WHERE state_hash=?', (_digest(state),))
    return flow


def _http_json(method, url, *, data=None, limit=512 * 1024):
    """Only fixed provider endpoints reach this function; never follow redirects."""
    try:
        with requests.request(method, url, data=data, timeout=(5, 15), allow_redirects=False,
                              stream=True, headers={'Accept': 'application/json'}) as response:
            if response.status_code != 200:
                raise ValueError('provider_request_failed')
            payload = bytearray()
            for chunk in response.iter_content(8192):
                payload.extend(chunk)
                if len(payload) > limit:
                    raise ValueError('provider_response_too_large')
            value = current_app.json.loads(payload.decode('utf-8'))
    except (requests.RequestException, UnicodeError) as exc:
        raise ValueError('provider_request_failed') from exc
    if not isinstance(value, dict):
        raise ValueError('invalid_provider_response')
    return value


def _exchange(config, code, verifier):
    result = _http_json('POST', config.token_endpoint, limit=64 * 1024, data={
        'client_id': config.client_id, 'client_secret': config.client_secret,
        'grant_type': 'authorization_code', 'redirect_uri': config.redirect_uri,
        'code': code, 'code_verifier': verifier,
    })
    token = result.get('id_token')
    if not isinstance(token, str) or not 1 <= len(token) <= 32768:
        raise ValueError('invalid_id_token')
    # Provider access/refresh tokens are deliberately discarded.
    return token


def _issuer(config, claims):
    if config.name == 'google':
        if claims.get('iss') not in {'https://accounts.google.com', 'accounts.google.com'}:
            raise ValueError('invalid_id_token')
        return claims['iss']
    tenant = claims.get('tid')
    if not isinstance(tenant, str) or not _GUID.fullmatch(tenant):
        raise ValueError('invalid_id_token')
    if ((_GUID.fullmatch(config.authority) and tenant != config.authority)
            or (config.authority == 'organizations' and tenant == _CONSUMER_TENANT)
            or (config.authority == 'consumers' and tenant != _CONSUMER_TENANT)):
        raise ValueError('invalid_id_token')
    issuer = 'https://login.microsoftonline.com/' + tenant + '/v2.0'
    if claims.get('iss') != issuer or claims.get('ver') != '2.0':
        raise ValueError('invalid_id_token')
    return issuer


def _verify(config, token, flow):
    """Use PyJWT's RSA backend and provider keys; unverified claims select no URLs."""
    try:
        header = jwt.get_unverified_header(token)
        if header.get('alg') != 'RS256' or not isinstance(header.get('kid'), str):
            raise ValueError('invalid_id_token')
        unverified = jwt.decode(token, options={'verify_signature': False})
        issuer = _issuer(config, unverified)
        keys = _http_json('GET', config.jwks_uri).get('keys')
        if not isinstance(keys, list) or len(keys) > 100:
            raise ValueError('invalid_provider_keys')
        candidates = [key for key in keys if isinstance(key, dict) and key.get('kid') == header['kid']
                      and key.get('kty') == 'RSA' and key.get('use', 'sig') == 'sig'
                      and key.get('alg', 'RS256') == 'RS256']
        if len(candidates) != 1:
            raise ValueError('invalid_provider_keys')
        key = candidates[0]
        if config.name == 'microsoft':
            key_issuer = key.get('issuer')
            if not isinstance(key_issuer, str) or key_issuer.replace('{tenantid}', unverified['tid']) != issuer:
                raise ValueError('invalid_provider_keys')
        rsa = jwt.algorithms.get_default_algorithms().get('RS256')
        if rsa is None:
            raise ValueError('provider_crypto_unavailable')
        public_key = rsa.from_jwk(json.dumps(key))
        if public_key.key_size < 2048:
            raise ValueError('invalid_provider_keys')
        claims = jwt.decode(token, public_key, algorithms=['RS256'], audience=config.client_id,
                            issuer=issuer, leeway=60,
                            options={'require': ['iss', 'aud', 'sub', 'exp', 'iat', 'nonce']})
        if _issuer(config, claims) != issuer:
            raise ValueError('invalid_id_token')
        if (not isinstance(claims['sub'], str) or not 1 <= len(claims['sub']) <= 255
                or not isinstance(claims['nonce'], str)
                or not hmac.compare_digest(claims['nonce'].encode(), flow['nonce'].encode())
                or any(isinstance(claims[key], bool) or not isinstance(claims[key], (int, float))
                       or not math.isfinite(claims[key]) for key in ('exp', 'iat'))
                or claims['iat'] < flow['created'] - 60 or claims['exp'] <= claims['iat']
                or ('azp' in claims and claims['azp'] != config.client_id)
                or (isinstance(claims['aud'], list) and len(claims['aud']) > 1
                    and claims.get('azp') != config.client_id)):
            raise ValueError('invalid_id_token')
    except (jwt.PyJWTError, KeyError, TypeError, OverflowError) as exc:
        raise ValueError('invalid_id_token') from exc
    # Google's documented equivalent issuer spellings refer to the same subject.
    return ('https://accounts.google.com' if config.name == 'google' else issuer), claims['sub']


def _save_link(config, user, issuer, subject):
    account = account_key(user)
    reference = json.dumps(_reference(user), separators=(',', ':'))
    with _database() as db:
        _tables(db)
        _execute(db, 'INSERT INTO oidc_links (provider,client_id,issuer,subject,account,identity,created) '
                 'VALUES (?,?,?,?,?,?,?) ON CONFLICT DO NOTHING',
                 (config.name, config.client_id, issuer, subject, account, reference, time.time()))
        row = _execute(db, 'SELECT account FROM oidc_links WHERE provider=? AND client_id=? AND issuer=? AND subject=?',
                       (config.name, config.client_id, issuer, subject)).fetchone()
        if not row or row[0] != account:
            raise ValueError('provider_already_linked')


def _link_user(flow):
    from service.security import _revision, management_user
    user = management_user()
    revision = _revision(user)
    if (not revision or not isinstance(flow['revision'], str)
            or not isinstance(flow['identity'], str) or not isinstance(flow['session_hash'], str)
            or not hmac.compare_digest(revision, flow['revision'])
            or _reference(user) != current_app.json.loads(flow['identity'])
            or not hmac.compare_digest(_digest(session['management_token']), flow['session_hash'])):
        raise ValueError('account_changed')
    return user


def finish(name, state, code, *, provider_error=False):
    from service.security import resolve_linked_account
    from service import account_mfa, trusted_devices
    config = _provider(name)
    if config is None:
        raise ValueError('provider_not_configured')
    flow = _consume_state(config, state)
    if provider_error or not isinstance(code, str) or not 1 <= len(code) <= 8192:
        raise ValueError('invalid_oidc_callback')
    if flow['intent'] == 'link':
        _link_user(flow)
    elif flow['intent'] != 'login':
        raise ValueError('invalid_oidc_state')
    issuer, subject = _verify(config, _exchange(config, code, flow['verifier']), flow)
    if flow['intent'] == 'link':
        # Provider requests may take several seconds: revalidate the linking session afterward.
        user = _link_user(flow)
        _save_link(config, user, issuer, subject)
        return 'linked', user, None
    with _database() as db:
        _tables(db)
        row = _execute(db, 'SELECT identity FROM oidc_links WHERE provider=? AND client_id=? AND issuer=? AND subject=?',
                       (name, config.client_id, issuer, subject)).fetchone()
    if not row:
        return 'not_linked', None, None
    reference = current_app.json.loads(row[0])
    user = resolve_linked_account(reference)
    if not user:
        raise ValueError('account_unavailable')
    tenant = user.get('tenant') or flow['tenant']
    # A provider cannot move a business account into the tenant supplied at login.
    if user.get('tenant') and user['tenant'] != flow['tenant']:
        raise ValueError('invalid_tenant')
    trusted = trusted_devices.verified_first_factor_login(user, tenant)
    if trusted:
        return 'signed_in', user, trusted
    account_mfa.begin(user, tenant)
    return 'mfa_required', user, None


def disconnect(name, user):
    if name not in PROVIDERS:
        raise ValueError('unknown_provider')
    with _database() as db:
        _tables(db)
        _execute(db, 'DELETE FROM oidc_links WHERE provider=? AND account=?', (name, account_key(user)))
