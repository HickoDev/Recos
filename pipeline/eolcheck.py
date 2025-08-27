#!/usr/bin/env python3
import json, os, sys, re, requests
from datetime import datetime
from typing import Dict, Any

# local scraper for End-of-Sale / End-of-Support info
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scraping'))
try:
    from eol_details import get_eol_details  # type: ignore
except Exception:
    get_eol_details = None  # fallback if selenium not available

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data')

DEVICES_JSON = os.path.join(DATA_DIR, "devices.json")
PID_ALIAS_JSON = os.path.join(DATA_DIR, "pid_alias.json")  # optional

def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _log(msg: str):
    print(msg, flush=True)

def main():
    _log("[eolcheck] Start")
    devices = load_json(DEVICES_JSON, {})
    if not isinstance(devices, dict) or not devices:
        _log(f"[eolcheck] [!] {DEVICES_JSON} is missing or empty.")
        sys.exit(1)

    pid_alias = load_json(PID_ALIAS_JSON, {})  # dict: PID -> marketing name (alias)
    _log(f"[eolcheck] Loaded {len(devices)} devices; {len(pid_alias)} PID aliases")

    _log("[eolcheck] Using Selenium details only (no legacy listing match)")

    updated = 0
    cache: Dict[str, Any] = {}
    for host, rec in devices.items():
        _log(f"[eolcheck] --- Device: {host} ---")
        pid = (rec.get("model") or "").strip()
        alias = (pid_alias.get(pid) or "").strip()
        _log(f"[eolcheck] [{host}] model='{pid or '-'}' alias='{alias or '-'}'")

        # New: attempt to fetch detailed dates via Selenium if available
        # We'll query by alias first (preferred), else pid/model.
        q = alias or pid
        if q and get_eol_details:
            if q not in cache:
                _log(f"[eolcheck] [{host}] Selenium details: fetching for '{q}'")
                try:
                    details = get_eol_details(q)
                except Exception:
                    details = None
                cache[q] = details
            details = cache.get(q)
            if details:
                _log(f"[eolcheck] [{host}] Selenium details: SUCCESS")
                if details.get('nav_steps'):
                    for step in details['nav_steps']:
                        _log(f"[eolcheck]    • {step}")
                _log(f"[eolcheck]    title: {details.get('nav_title')}")
                _log(f"[eolcheck]    url:   {details.get('nav_url')}")
                _log(f"[eolcheck]    Status: {details.get('status')}")
                _log(f"[eolcheck]    Series Release Date: {details.get('series_release_date')}")
                _log(f"[eolcheck]    End-of-Sale:    {details.get('end_of_sale_date')}")
                _log(f"[eolcheck]    End-of-Support: {details.get('end_of_support_date')}")
                rec["eol_details"] = {
                    "end_of_sale_date": details.get("end_of_sale_date"),
                    "end_of_support_date": details.get("end_of_support_date"),
                    "series_release_date": details.get("series_release_date"),
                    "status": details.get("status"),
                    "nav_title": details.get("nav_title"),
                    "nav_url": details.get("nav_url"),
                    "nav_steps": details.get("nav_steps"),
                    "alias_used": alias or None,
                }
            else:
                _log(f"[eolcheck] [{host}] Selenium details: NOT FOUND")
        elif q and not get_eol_details:
            _log(f"[eolcheck] [{host}] Selenium not available, skipping detailed dates")
        else:
            _log(f"[eolcheck] [{host}] No alias/model to query for detailed dates")

        devices[host] = rec
        updated += 1

    with open(DEVICES_JSON, "w", encoding="utf-8") as f:
        json.dump(devices, f, indent=2, ensure_ascii=False)
    _log(f"[eolcheck] [✓] Updated {updated} records in {DEVICES_JSON}")
    _log("[eolcheck] Done")

if __name__ == "__main__":
    main()
