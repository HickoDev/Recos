#!/usr/bin/env python3
"""FastAPI dashboard API for retrievos historical snapshots.

Endpoints:
  GET /api/batches                      → list batch timestamps (newest first)
  GET /api/batch/{ts}/devices          → all device rows for given batch
  GET /api/batch/{ts}/cves             → CVE detailed rows for batch
  GET /api/device/{host}/timeline      → per-batch condensed timeline for one device
  GET /api/latest                      → devices for most recent batch
  GET /api/batch/{ts}/log              → pipeline log text for batch
  GET /api/batch/{ts}/mail             → raw email (if archived) for batch

Assumes history_writer.py has produced JSONL snapshot files.
"""
from __future__ import annotations
import os, json
from fastapi import FastAPI, HTTPException, Body, Request, Depends
from fastapi.responses import PlainTextResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from typing import List, Dict, Any
import subprocess
import threading
import time
import shlex
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import JSONResponse
from dotenv import load_dotenv
import secrets
import hmac
import hashlib

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Load environment from .env if present
load_dotenv(os.path.join(BASE_DIR, '.env'))
DATA_DIR = os.path.join(BASE_DIR, 'data')
HIST_DIR = os.path.join(DATA_DIR, 'history')
LOGS_DIR = os.path.join(HIST_DIR, 'logs')
MAILS_DIR = os.path.join(HIST_DIR, 'mails')
SCRIPTS_DIR = os.path.join(BASE_DIR, 'scripts')
ANSIBLE_DIR = os.path.join(BASE_DIR, 'ansible')
ANSIBLE_INVENTORY = os.path.join(ANSIBLE_DIR, 'inventory.ini')
ANSIBLE_INVENTORY_TMP = os.path.join(ANSIBLE_DIR, 'inventory.decrypted.ini')

DEVICES_SNAPSHOT = os.path.join(HIST_DIR, 'devices_snapshot.jsonl')
CVES_SNAPSHOT = os.path.join(HIST_DIR, 'cves_snapshot.jsonl')
BATCHES_JSONL = os.path.join(HIST_DIR, 'batches.jsonl')
PID_ALIAS_JSON = os.path.join(DATA_DIR, 'pid_alias.json')

STATIC_DIR = os.path.join(os.path.dirname(__file__), 'static')
FRONTEND_DIST = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'frontend', 'dist')
os.makedirs(STATIC_DIR, exist_ok=True)

# Inventory crypto utils (load by path to avoid clashing with external 'ansible' pkg)
def _load_inventory_crypto():
    try:
        import importlib.util
        path = os.path.join(ANSIBLE_DIR, 'inventory_crypto.py')
        spec = importlib.util.spec_from_file_location('inventory_crypto_local', path)
        if not spec or not spec.loader:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore
        return mod
    except Exception:
        return None

_inv_crypto = _load_inventory_crypto()
if _inv_crypto is not None:
    encrypt_password = getattr(_inv_crypto, 'encrypt_password')
    decrypt_password = getattr(_inv_crypto, 'decrypt_password')
    decrypt_inventory_text = getattr(_inv_crypto, 'decrypt_inventory_text')
else:
    def encrypt_password(x: str) -> str:  # type: ignore
        return x
    def decrypt_password(x: str) -> str:  # type: ignore
        return x
    def decrypt_inventory_text(x: str) -> str:  # type: ignore
        return x

app = FastAPI(title="retrievos dashboard API", version="0.1.0")
# Session middleware for simple cookie-based auth
SECRET_KEY = os.getenv('SECRET_KEY') or 'dev-insecure-secret-key'
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    session_cookie='retrievos_session',
    same_site='lax',
    https_only=False,
)
app.mount('/static', StaticFiles(directory=STATIC_DIR), name='static')
if os.path.isdir(FRONTEND_DIST):
    app.mount('/app', StaticFiles(directory=FRONTEND_DIST), name='app')
    assets_dir = os.path.join(FRONTEND_DIST, 'assets')
    if os.path.isdir(assets_dir):
        app.mount('/assets', StaticFiles(directory=assets_dir), name='assets')

def _read_jsonl(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        return []
    out = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out

def _load_json(path: str, default):
    try:
        if not os.path.exists(path):
            return default
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default

def _save_json(path: str, data: Any):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def _unique_sorted_batches() -> List[str]:
    rows = _read_jsonl(BATCHES_JSONL)
    ts = {r.get('batch_ts') for r in rows if r.get('batch_ts')}
    return sorted(ts, reverse=True)

def _batch_summaries(limit: int | None = None) -> List[Dict[str, Any]]:
    rows = _read_jsonl(BATCHES_JSONL)
    # ensure proper sort newest first
    rows = [r for r in rows if r.get('batch_ts')]
    rows.sort(key=lambda r: r['batch_ts'], reverse=True)
    if limit:
        rows = rows[:limit]
    return rows

def _devices_for_batch(ts: str):
    rows = _read_jsonl(DEVICES_SNAPSHOT)
    return [r for r in rows if r.get('batch_ts') == ts]

def _cves_for_batch(ts: str):
    rows = _read_jsonl(CVES_SNAPSHOT)
    result = [r for r in rows if r.get('batch_ts') == ts]
    # Augment CVE entries with URLs for NVD and Cisco advisory/search if missing
    for r in result:
        cves = r.get('cves') or {}
        for sev, items in list(cves.items()):
            new_items = []
            for item in items or []:
                # tolerate both string and object forms
                if isinstance(item, str):
                    cve_id = item.strip()
                    new_items.append({
                        'id': cve_id,
                        'title': cve_id,
                        'nvd_url': f'https://nvd.nist.gov/vuln/detail/{cve_id}' if cve_id else None,
                        'cisco_url': f'https://tools.cisco.com/security/center/search.x?search={cve_id}' if cve_id else None,
                    })
                    continue
                if isinstance(item, dict):
                    cve_id = (item.get('id') or '').strip()
                    # preserve existing fields, derive missing urls
                    obj = dict(item)
                    obj.setdefault('nvd_url', f'https://nvd.nist.gov/vuln/detail/{cve_id}' if cve_id else None)
                    if not obj.get('cisco_url'):
                        obj['cisco_url'] = f'https://tools.cisco.com/security/center/search.x?search={cve_id}' if cve_id else None
                    new_items.append(obj)
                else:
                    new_items.append(item)
            cves[sev] = new_items
        r['cves'] = cves
    return result

def _timeline_for_host(host: str):
    rows = _read_jsonl(DEVICES_SNAPSHOT)
    tl = []
    for r in rows:
        if r.get('host') == host:
            tl.append({
                'batch_ts': r.get('batch_ts'),
                'version': r.get('current_version'),
                'recommended_version': r.get('recommended_version'),
                'release_designation': r.get('release_designation'),
                'upgrade_recommended': r.get('upgrade_recommended'),
                'recommendation': r.get('recommendation'),
                'final_url': r.get('final_url'),
                'critical_cves': (r.get('cve_counts') or {}).get('Critical'),
                'high_cves': (r.get('cve_counts') or {}).get('High'),
                'cpu_usage': r.get('cpu_usage'),
                'status': r.get('status'),
                'series_release_date': r.get('series_release_date'),
                'end_of_sale_date': r.get('end_of_sale_date'),
                'end_of_support_date': r.get('end_of_support_date'),
            })
    tl.sort(key=lambda x: x['batch_ts'])
    return tl

# === Simple session-based auth ===
ADMIN_USER = (os.getenv('ADMIN_USER', 'admin') or '').strip()
ADMIN_PASSWORD = (os.getenv('ADMIN_PASSWORD', '') or '').strip()

def _consteq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode('utf-8'), b.encode('utf-8'))

def _hash_pw(pw: str, salt: str) -> str:
    # PBKDF2-HMAC-SHA256; note: for this simple setup we keep salt constant = ADMIN_USER
    dk = hashlib.pbkdf2_hmac('sha256', pw.encode('utf-8'), salt.encode('utf-8'), 100_000)
    return dk.hex()

def _verify_credentials(username: str, password: str) -> bool:
    if not username or not password:
        return False
    if not ADMIN_PASSWORD:
        # If no ADMIN_PASSWORD set, deny login (forces configuration)
        return False
    # Support either plain compare (DEV) or pre-hashed value (prefix 'pbkdf2:')
    if ADMIN_PASSWORD.startswith('pbkdf2:'):
        expected = ADMIN_PASSWORD.split(':', 1)[1]
        return _consteq(_hash_pw(password, ADMIN_USER), expected) and _consteq(username, ADMIN_USER)
    # Plaintext fallback (not recommended for prod)
    return _consteq(username, ADMIN_USER) and _consteq(password, ADMIN_PASSWORD)

def require_login(request: Request):
    user = (request.session or {}).get('user') if hasattr(request, 'session') else None
    if not user:
        raise HTTPException(status_code=401, detail='not authenticated')
    return user

@app.post('/api/auth/login')
async def auth_login(payload: Dict[str, Any] = Body(...), request: Request = None):
    username = (payload or {}).get('username') or ''
    password = (payload or {}).get('password') or ''
    if not _verify_credentials(username.strip(), password):
        raise HTTPException(status_code=401, detail='invalid credentials')
    # Regenerate a simple session token
    token = secrets.token_urlsafe(24)
    request.session['user'] = {'name': ADMIN_USER, 'token': token}
    return {'ok': True, 'user': {'name': ADMIN_USER}}

@app.post('/api/auth/logout')
async def auth_logout(request: Request, user: Dict[str, Any] = Depends(require_login)):
    request.session.clear()
    return {'ok': True}

@app.get('/api/auth/me')
async def auth_me(request: Request):
    user = (request.session or {}).get('user') if hasattr(request, 'session') else None
    if not user:
        return JSONResponse({'authenticated': False}, status_code=200)
    return {'authenticated': True, 'user': {'name': user.get('name')}}

@app.get('/api/batches')
def list_batches():
    return {'batches': _unique_sorted_batches()}

@app.get('/api/batch_summaries')
def batch_summaries(limit: int = 50):
    """Return recent batch summary metrics (newest first)."""
    rows = _batch_summaries(limit=limit)
    return {'summaries': rows}

def _latest_batch():
    bs = _unique_sorted_batches()
    return bs[0] if bs else None

@app.get('/api/latest')
def latest_devices():
    lb = _latest_batch()
    if not lb:
        return {'devices': [], 'batch_ts': None}
    return {'devices': _devices_for_batch(lb), 'batch_ts': lb}

@app.get('/api/batch/{ts}/devices')
def batch_devices(ts: str):
    rows = _devices_for_batch(ts)
    if not rows:
        raise HTTPException(status_code=404, detail='batch not found or empty')
    return {'devices': rows, 'batch_ts': ts}

@app.get('/api/batch/{ts}/cves')
def batch_cves(ts: str):
    rows = _cves_for_batch(ts)
    if not rows:
        raise HTTPException(status_code=404, detail='batch not found or empty')
    return {'cves': rows, 'batch_ts': ts}

@app.get('/api/device/{host}/timeline')
def device_timeline(host: str):
    tl = _timeline_for_host(host)
    if not tl:
        raise HTTPException(status_code=404, detail='device not found')
    return {'host': host, 'timeline': tl}

# === PID alias management ===
@app.get('/api/pid_alias')
def get_pid_alias():
    mapping = _load_json(PID_ALIAS_JSON, {})
    return {'pid_alias': mapping}

@app.post('/api/pid_alias')
def add_pid_alias(pid: str = Body(...), alias: str = Body(...), user: Dict[str, Any] = Depends(require_login)):
    pid = (pid or '').strip()
    alias = (alias or '').strip()
    if not pid or not alias:
        raise HTTPException(status_code=400, detail='pid and alias are required')
    mapping = _load_json(PID_ALIAS_JSON, {})
    if not isinstance(mapping, dict):
        mapping = {}
    mapping[pid] = alias
    _save_json(PID_ALIAS_JSON, mapping)
    return {'ok': True, 'pid': pid, 'alias': alias}

@app.get('/api/pid_alias/{pid}')
def get_pid_alias_one(pid: str):
    mapping = _load_json(PID_ALIAS_JSON, {})
    val = (mapping or {}).get(pid)
    if not val:
        raise HTTPException(status_code=404, detail='pid not found')
    return {'pid': pid, 'alias': val}

# === Run pipeline orchestrator ===
_run_lock = threading.Lock()
_run_proc: subprocess.Popen | None = None
_run_mode: str | None = None
_run_started_at: float | None = None
_last_run_ts: str | None = None
_orch_log_path: str | None = None

def _tail_file(path: str, max_bytes: int = 4096) -> str | None:
    try:
        if not os.path.exists(path):
            return None
        size = os.path.getsize(path)
        with open(path, 'rb') as f:
            if size > max_bytes:
                f.seek(-max_bytes, os.SEEK_END)
            data = f.read().decode('utf-8', errors='replace')
        return data
    except Exception:
        return None

def _check_proc():
    global _run_proc, _run_mode, _run_started_at, _last_run_ts
    if _run_proc is not None:
        if _run_proc.poll() is not None:
            # finished
            _run_proc = None
            _run_mode = None
            _run_started_at = None
            # try detect last run ts from batches file (latest)
            bs = _unique_sorted_batches()
            _last_run_ts = bs[0] if bs else None

def _compute_progress(mode: str | None, text: str | None) -> dict:
    t = (text or '')
    if mode == 'no-ansible':
        total = 5
        if 'Writing history snapshots' in t or 'Done' in t:
            return {'current': 5, 'total': total, 'label': 'Writing history snapshots'}
        if 'Mail Notification' in t:
            return {'current': 4, 'total': total, 'label': 'Mail Notification'}
        if 'Running scraping pipeline' in t:
            return {'current': 3, 'total': total, 'label': 'Scraping pipeline'}
        if 'Checking end of life status' in t:
            return {'current': 2, 'total': total, 'label': 'End of life check'}
        if 'Running CVEs check' in t:
            return {'current': 1, 'total': total, 'label': 'CVE check'}
        return {'current': 1, 'total': total, 'label': 'Starting…'}
    else:
        total = 5
        if 'Writing history snapshots' in t or 'Done' in t:
            return {'current': 5, 'total': total, 'label': 'Writing history snapshots'}
        if 'Running scraping pipeline' in t:
            return {'current': 4, 'total': total, 'label': 'Scraping pipeline'}
        if 'Checking end of life status' in t:
            return {'current': 3, 'total': total, 'label': 'End of life check'}
        if 'Running CVEs check' in t:
            return {'current': 2, 'total': total, 'label': 'CVE check'}
        if 'Running NXOS playbook' in t or 'Running IOS playbook' in t:
            return {'current': 1, 'total': total, 'label': 'Ansible playbooks'}
        return {'current': 1, 'total': total, 'label': 'Starting…'}

@app.get('/api/run/status')
def run_status():
    _check_proc()
    running = _run_proc is not None
    orch_tail = _tail_file(_orch_log_path) if _orch_log_path else None
    prog = _compute_progress(_run_mode, orch_tail)
    return {
        'running': running,
        'mode': _run_mode,
        'started_at': _run_started_at,
        'last_run_ts': _last_run_ts,
        'orch_tail': orch_tail,
        'progress_current': prog['current'],
        'progress_total': prog['total'],
        'progress_label': prog['label'],
    }

@app.post('/api/run')
async def start_run(request: Request, user: Dict[str, Any] = Depends(require_login)):
    """
    Start a new pipeline run.
    mode: 'full' (with Ansible) or 'no-ansible'
    """
    global _run_proc, _run_mode, _run_started_at
    # Accept either a raw JSON string body ("full") or an object {"mode": "full"}; default to 'full' on parse failure
    raw_mode = None
    try:
        payload = await request.json()
    except Exception:
        payload = None
    if isinstance(payload, str):
        raw_mode = payload
    elif isinstance(payload, dict):
        raw_mode = payload.get('mode')
    m = (raw_mode or 'full').strip().lower()
    if m not in {'full', 'no-ansible'}:
        raise HTTPException(status_code=400, detail="mode must be 'full' or 'no-ansible'")
    with _run_lock:
        _check_proc()
        if _run_proc is not None:
            raise HTTPException(status_code=409, detail='a run is already in progress')
        script = os.path.join(SCRIPTS_DIR, 'orchestrate.sh' if m == 'full' else 'orchestrate_no_ansible.sh')
        if not os.path.exists(script):
            raise HTTPException(status_code=500, detail='orchestrate script not found')
        try:
            # route orchestrator output to a log file for live feedback
            global _orch_log_path
            _orch_log_path = os.path.join(DATA_DIR, 'orchestrate_current.log')
            logf = open(_orch_log_path, 'wb')
            _run_proc = subprocess.Popen(['bash', script], cwd=BASE_DIR, stdout=logf, stderr=logf)
            _run_mode = m
            _run_started_at = time.time()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f'failed to start run: {e}')
    return {'started': True, 'mode': _run_mode, 'pid': _run_proc.pid if _run_proc else None, 'started_at': _run_started_at}

@app.get('/api/batch/{ts}/log')
def batch_log(ts: str):
    log_path = os.path.join(LOGS_DIR, f'run_pipeline_{ts}.log')
    if not os.path.exists(log_path):
        raise HTTPException(status_code=404, detail='log not found')
    with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()
    return PlainTextResponse(content)

@app.get('/api/batch/{ts}/mail')
def batch_mail(ts: str):
    mail_path = os.path.join(MAILS_DIR, f'notification_{ts}.eml')
    if not os.path.exists(mail_path):
        raise HTTPException(status_code=404, detail='mail not found')
    with open(mail_path, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()
    return PlainTextResponse(content, media_type='message/rfc822')

# === Ansible inventory management ===
def _parse_inventory(path: str) -> Dict[str, List[Dict[str, Any]]]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    if not os.path.exists(path):
        return groups
    current: str | None = None
    with open(path, 'r', encoding='utf-8') as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith('#') or line.startswith(';'):
                continue
            if line.startswith('[') and line.endswith(']'):
                current = line[1:-1].strip()
                groups.setdefault(current, [])
                continue
            if not current:
                continue
            try:
                parts = shlex.split(line)
            except Exception:
                parts = line.split()
            if not parts:
                continue
            host = parts[0]
            vars: Dict[str, str] = {}
            for tok in parts[1:]:
                if '=' in tok:
                    k, v = tok.split('=', 1)
                    vars[k] = v
            groups.setdefault(current, []).append({'host': host, 'vars': vars})
    return groups

def _write_inventory(path: str, groups: Dict[str, List[Dict[str, Any]]]):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines: List[str] = []
    # Write groups in a stable order, but keep ios/nxos first if present
    ordered = []
    for g in ['ios', 'nxos']:
        if g in groups:
            ordered.append(g)
    for g in sorted(groups.keys()):
        if g not in ordered:
            ordered.append(g)
    for g in ordered:
        lines.append(f'[{g}]')
        entries = groups.get(g) or []
        for entry in entries:
            host = entry.get('host') or ''
            v = entry.get('vars') or {}
            # Prefer common Ansible keys first
            keys_pref = ['ansible_host', 'ansible_user', 'ansible_password', 'ansible_network_os', 'ansible_connection']
            other_keys = sorted([k for k in v.keys() if k not in keys_pref])
            key_order = [k for k in keys_pref if k in v] + other_keys
            # Encrypt ansible_password if present and not already encoded
            if 'ansible_password' in v and v['ansible_password']:
                v = dict(v)
                v['ansible_password'] = encrypt_password(str(v['ansible_password']))
            kv = ' '.join([f"{k}={v[k]}" for k in key_order])
            line = host if not kv else f"{host} {kv}"
            lines.append(line)
        lines.append('')  # blank line between groups
    content = '\n'.join(lines).rstrip() + '\n'
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)

@app.get('/api/inventory')
def get_inventory():
    groups = _parse_inventory(ANSIBLE_INVENTORY)
    # Redact passwords for UI
    for hosts in groups.values():
        for entry in hosts:
            vars = entry.get('vars') or {}
            if 'ansible_password' in vars and vars['ansible_password']:
                vars['ansible_password'] = '********'
    return {'groups': groups}

@app.get('/api/inventory/{group}')
def get_inventory_group(group: str):
    groups = _parse_inventory(ANSIBLE_INVENTORY)
    if group not in groups:
        raise HTTPException(status_code=404, detail='group not found')
    # Redact passwords
    hosts = groups[group]
    for entry in hosts:
        vars = entry.get('vars') or {}
        if 'ansible_password' in vars and vars['ansible_password']:
            vars['ansible_password'] = '********'
    return {'group': group, 'hosts': hosts}

@app.post('/api/inventory/host')
def upsert_inventory_host(group: str = Body(...), host: str = Body(...), vars: Dict[str, Any] = Body(default={}), user: Dict[str, Any] = Depends(require_login)):  # type: ignore[override]
    group = (group or '').strip()
    host = (host or '').strip()
    if not group or not host:
        raise HTTPException(status_code=400, detail='group and host are required')
    groups = _parse_inventory(ANSIBLE_INVENTORY)
    arr = groups.setdefault(group, [])
    # Build merged vars if host exists
    idx = next((i for i,e in enumerate(arr) if (e.get('host') or '') == host), None)
    incoming = vars or {}
    if idx is not None:
        current_vars = dict(arr[idx].get('vars') or {})
        # If UI sent masked or empty password, keep existing
        pw_in = str(incoming.get('ansible_password', '') or '')
        if not pw_in or pw_in == '********':
            if 'ansible_password' in incoming:
                incoming = dict(incoming)
                incoming.pop('ansible_password', None)
        merged = current_vars
        merged.update(incoming)
        arr[idx]['vars'] = merged
    else:
        # New entry: accept as is; if password empty/masked, omit field
        incoming = dict(incoming)
        pw_in = str(incoming.get('ansible_password', '') or '')
        if not pw_in or pw_in == '********':
            incoming.pop('ansible_password', None)
        arr.append({'host': host, 'vars': incoming})
    try:
        _write_inventory(ANSIBLE_INVENTORY, groups)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'failed to write inventory: {e}')
    # Do not echo back the password
    if vars and 'ansible_password' in vars:
        vars = dict(vars)
        vars['ansible_password'] = '********'
    return {'ok': True, 'group': group, 'host': host, 'vars': vars or {}}

@app.delete('/api/inventory/host')
def delete_inventory_host(group: str = Body(...), host: str = Body(...), user: Dict[str, Any] = Depends(require_login)):
    group = (group or '').strip()
    host = (host or '').strip()
    if not group or not host:
        raise HTTPException(status_code=400, detail='group and host are required')
    groups = _parse_inventory(ANSIBLE_INVENTORY)
    if group not in groups:
        raise HTTPException(status_code=404, detail='group not found')
    prior = len(groups[group])
    groups[group] = [e for e in (groups[group] or []) if (e.get('host') or '') != host]
    if len(groups[group]) == prior:
        raise HTTPException(status_code=404, detail='host not found')
    try:
        _write_inventory(ANSIBLE_INVENTORY, groups)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'failed to write inventory: {e}')
    return {'ok': True, 'group': group, 'host': host}

@app.get('/')
def serve_index():
    # Prefer Vue app if built; else fall back to classic static index.html
    spa_index = os.path.join(FRONTEND_DIST, 'index.html')
    if os.path.exists(spa_index):
        return FileResponse(spa_index)
    index_path = os.path.join(STATIC_DIR, 'index.html')
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {'service': 'retrievos-dashboard', 'warning': 'no frontend found', 'endpoints': '/api/batches /api/latest ...'}

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8000)
