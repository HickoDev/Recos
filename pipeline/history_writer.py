#!/usr/bin/env python3
"""Write append-only historical snapshots for each batch run.

Requires RUN_TS environment variable (UTC ISO) exported by orchestrator.
Generates/updates these append-only JSONL files under data/history/:
  devices_snapshot.jsonl  (one line per device per batch)
  cves_snapshot.jsonl     (one line per device per batch including full CVE lists)
  batches.jsonl           (one line per batch summary)

Also copies the run_pipeline.log to data/history/logs/run_pipeline_<RUN_TS>.log
If an email raw file is produced (email_last.eml), it will be copied/renamed similarly.
"""
from __future__ import annotations
import os, json, sys, shutil
from typing import Dict, Any

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data')
HIST_DIR = os.path.join(DATA_DIR, 'history')
LOGS_DIR = os.path.join(HIST_DIR, 'logs')
MAILS_DIR = os.path.join(HIST_DIR, 'mails')

DEVICES_JSON = os.path.join(DATA_DIR, 'devices.json')
CVE_JSON = os.path.join(DATA_DIR, 'device_cve_check.json')
UPGRADE_JSON = os.path.join(DATA_DIR, 'upgrade-suggestions.json')
PIPELINE_LOG = os.path.join(DATA_DIR, 'run_pipeline.log')

DEVICES_SNAPSHOT = os.path.join(HIST_DIR, 'devices_snapshot.jsonl')
CVES_SNAPSHOT = os.path.join(HIST_DIR, 'cves_snapshot.jsonl')
BATCHES_JSONL = os.path.join(HIST_DIR, 'batches.jsonl')

def load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default

def write_jsonl_line(path: str, obj: Dict[str, Any]):
    with open(path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(obj, ensure_ascii=False) + '\n')

def main():
    run_ts = os.getenv('RUN_TS')
    if not run_ts:
        print('[history] RUN_TS not set; aborting to avoid untagged snapshot.', file=sys.stderr)
        sys.exit(1)

    if 'T' not in run_ts:
        print('[history] RUN_TS format unexpected; continue anyway.', file=sys.stderr)

    os.makedirs(HIST_DIR, exist_ok=True)
    os.makedirs(LOGS_DIR, exist_ok=True)
    os.makedirs(MAILS_DIR, exist_ok=True)

    devices = load_json(DEVICES_JSON, {})
    cve_map = load_json(CVE_JSON, {})
    upgrades = load_json(UPGRADE_JSON, [])

    # Build upgrade suggestion mapping:
    #  1. collect latest entry per host (fallback_latest)
    #  2. collect exact batch matches (checked_at == run_ts)
    upgrades_for_batch = {}
    fallback_latest = {}
    if isinstance(upgrades, list):
        for row in upgrades:
            if not isinstance(row, dict):
                continue
            host = row.get('host')
            if not host:
                continue
            fallback_latest[host] = row  # last one wins (list is append-only chronological)
            if row.get('checked_at') == run_ts:
                upgrades_for_batch[host] = row
    # Fill any host lacking an exact batch row with its latest fallback
    for h, r in fallback_latest.items():
        upgrades_for_batch.setdefault(h, r)

    device_count = 0
    devices_with_upgrade = 0
    devices_with_critical = 0
    devices_eol = 0
    total_high = 0
    total_medium = 0

    def cve_counts_for(host: str):
        rec = cve_map.get(host) or {}
        severities = rec.get('cves') or {}
        counts = {s: len(severities.get(s, [])) for s in ['Critical','High','Medium','Low']}
        return counts, severities

    for host, rec in (devices or {}).items():
        if not isinstance(rec, dict):
            continue
        device_count += 1
        upg = upgrades_for_batch.get(host)
        alias_name = upg.get('switch_name') if upg else None
        if upg and upg.get('upgrade_recommended'):
            devices_with_upgrade += 1
        counts, severities_map = cve_counts_for(host)
        if counts['Critical'] > 0:
            devices_with_critical += 1
        total_high += counts['High']
        total_medium += counts['Medium']
        # Prefer EoL fields from the upgrade suggestion row for this batch (written by run_pipeline.py),
        # then fall back to devices.json eol_details if not present.
        eol_details = {}
        if upg:
            eol_details = {
                'end_of_sale_date': upg.get('end_of_sale_date'),
                'end_of_support_date': upg.get('end_of_support_date'),
                'series_release_date': upg.get('series_release_date'),
                'status': upg.get('status'),
            }
        if not (eol_details.get('end_of_sale_date') or eol_details.get('end_of_support_date') or eol_details.get('status') or eol_details.get('series_release_date')):
            eol_details = rec.get('eol_details') or {}
        status_txt = (eol_details.get('status') or '').lower()
        eos_date = eol_details.get('end_of_sale_date')
        eosup_date = eol_details.get('end_of_support_date')
        if ('end of sale' in status_txt) or eosup_date:
            devices_eol += 1

        dev_info = rec.get('device_info') or {}
        iface = rec.get('interface_summary') or {}
        vlan = rec.get('vlan_summary') or {}
        perf = rec.get('performance_info') or {}

        # Normalize some numeric-like fields that arrived as strings
        def _as_int(x):
            try:
                return int(str(x))
            except Exception:
                return None
        cpu_val = perf.get('cpu_usage') or perf.get('cpu_5_sec') or perf.get('cpu_1_min') or perf.get('cpu_5_min')
        row = {
                'batch_ts': run_ts,
                'host': host,
                'alias_name': alias_name,
                'model': rec.get('model'),
                'platform': rec.get('platform'),
                'current_version': rec.get('version'),
                'platform_version': dev_info.get('nxos_version') or dev_info.get('ios_version') or rec.get('version'),
                'recommended_version': upg.get('recommended_version') if upg else None,
                'release_designation': upg.get('release_designation') if upg else None,
                'recommendation': upg.get('recommendation') if upg else None,
                'upgrade_recommended': upg.get('upgrade_recommended') if upg else None,
                'final_url': upg.get('final_url') if upg else None,
                'scraped_version_raw': upg.get('scraped_version_raw') if upg else None,
                'serial_number': dev_info.get('serial_number'),
                'uptime': dev_info.get('uptime'),
                'connected_ports': iface.get('connected_ports'),
                'connected_count': _as_int(iface.get('connected')),
                'disconnected_count': _as_int(iface.get('disconnected')),
                'total_interfaces': _as_int(iface.get('total_interfaces')),
                'cpu_usage': str(cpu_val) if cpu_val is not None else None,
                'vlan_active_count': vlan.get('total_active_vlans'),
                'vlans': vlan.get('vlans'),
                'end_of_sale_date': eol_details.get('end_of_sale_date'),
                'end_of_support_date': eol_details.get('end_of_support_date'),
                'series_release_date': eol_details.get('series_release_date'),
                'status': eol_details.get('status'),
                'cve_counts': counts,
            }
        write_jsonl_line(DEVICES_SNAPSHOT, row)

        cve_row = {
                'batch_ts': run_ts,
                'host': host,
                'current_version': rec.get('version'),
                'cve_counts': counts,
                'cves': severities_map,
        }
        write_jsonl_line(CVES_SNAPSHOT, cve_row)

    batch_summary = {
        'batch_ts': run_ts,
        'device_count': device_count,
        'devices_with_upgrade_recommended': devices_with_upgrade,
        'devices_with_critical_cves': devices_with_critical,
        'devices_eol': devices_eol,
        'total_high_cves': total_high,
        'total_medium_cves': total_medium,
    }
    write_jsonl_line(BATCHES_JSONL, batch_summary)

    if os.path.exists(PIPELINE_LOG):
        shutil.copy2(PIPELINE_LOG, os.path.join(LOGS_DIR, f'run_pipeline_{run_ts}.log'))

    last_mail = os.path.join(DATA_DIR, 'email_last.eml')
    if os.path.exists(last_mail):
        shutil.copy2(last_mail, os.path.join(MAILS_DIR, f'notification_{run_ts}.eml'))

    print(f'[history] Snapshot written for batch {run_ts}')

if __name__ == '__main__':
    main()
