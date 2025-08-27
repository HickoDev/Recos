#!/usr/bin/env python3
import os, json, sys, re, logging, time
from typing import Tuple, Optional
import re

# ✅ use your headless versions
import os, sys, json, logging, time, re
from typing import Tuple, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRAPING_DIR = os.path.join(BASE_DIR, 'scraping')
DATA_DIR = os.path.join(BASE_DIR, 'data')

sys.path.insert(0, SCRAPING_DIR)

from cisco_url_extractor import extract_url_for_model  # type: ignore
from last_version_extract import scrape_latest_version  # type: ignore
from datetime import datetime, timezone


# ==== CONFIG ====
DEVICES_JSON = os.path.join(DATA_DIR, "devices.json")                 # input
PID_ALIAS_JSON = os.path.join(DATA_DIR, "pid_alias.json")             # input
OUT_JSON = os.path.join(DATA_DIR, "upgrade-suggestions.json")         # output
LOG_FILE = os.path.join(DATA_DIR, "run_pipeline.log")

# Retry settings (for transient CDN/JS/render timing issues)
MAX_RETRIES_URL = 3
MAX_RETRIES_SCRAPE = 3
BACKOFF_BASE_SEC = 2.0  # exponential backoff: base^attempt (1,2,4,...)

# ==== LOGGING ====
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
console = logging.StreamHandler(sys.stdout)
console.setLevel(logging.INFO)
console.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logging.getLogger("").addHandler(console)

# ==== REGEX ====
RE_REC_SUFFIX = re.compile(r"\(\s*rec+omm?ended\s*\)\s*$", re.IGNORECASE)
RE_DESIG_SUFFIX = re.compile(r"\(\s*(MD|GD|ED|LD|DF|F|M)\s*\)\s*$", re.IGNORECASE)

# Version normalization helpers
RE_IOS_PAREN = re.compile(r"^(\d+)\.(\d+)\((\d+)\)([A-Za-z]+)?(\d+)?$")
RE_IOS_DASH = re.compile(r"^(\d+)\.(\d+)\.(\d+)-([A-Za-z]+)(\d+)$")
RE_IOS_DASH_SHORT = re.compile(r"^(\d+)\.(\d+)\.(\d+)([A-Za-z]+)(\d+)$")

def to_ios_canonical(v: str) -> str:
    """Convert common IOS forms like '15.0.2-SE11' or '15.2.7E9' to '15.0(2)SE11'/'15.2(7)E9'.
    If already canonical, return as-is. Best-effort; returns input on unknowns.
    """
    s = (v or "").strip()
    if not s:
        return s
    # already canonical
    m = RE_IOS_PAREN.match(s)
    if m:
        return s
    # dotted-dash: 15.0.2-SE11 -> 15.0(2)SE11
    m = RE_IOS_DASH.match(s)
    if m:
        a,b,c,sfx,n = m.groups()
        return f"{a}.{b}({c}){sfx}{n}"
    # dotted with no dash: 15.2.7E9 -> 15.2(7)E9
    m = RE_IOS_DASH_SHORT.match(s)
    if m:
        a,b,c,sfx,n = m.groups()
        return f"{a}.{b}({c}){sfx}{n}"
    return s

def normalize_version_by_platform(v: str, platform: Optional[str]) -> str:
    if not v:
        return v
    p = (platform or '').lower()
    if p == 'ios' or p == 'iosxe' or p == 'ios-xe':
        return to_ios_canonical(v)
    # NX-OS and others: leave as-is (already standard like 10.3(3))
    return v

def load_json(path, default):
    if not os.path.exists(path):
        logging.warning(f"{path} not found. Using default.")
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        logging.warning(f"{path} is not valid JSON. Using default.")
        return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logging.info(f"Saved updates to {path}")

def parse_version_meta(raw: str) -> Tuple[str, bool, Optional[str]]:
    """
    Strip '(recommended)' and designation suffixes like (MD/GD/DF...).
    Return (clean_version, is_explicit_rec, designation).
    """
    if not raw:
        return "", False, None
    s = raw.strip()
    is_explicit_rec = bool(RE_REC_SUFFIX.search(s))
    s = RE_REC_SUFFIX.sub("", s).rstrip()
    m = RE_DESIG_SUFFIX.search(s)
    designation = m.group(1).upper() if m else None
    s = RE_DESIG_SUFFIX.sub("", s).rstrip()
    return s, is_explicit_rec, designation

def decide_recommendation(current: str, latest: str, is_explicit_rec: bool, designation: Optional[str], platform: Optional[str] = None):
    """
    Return (recommendation_text, upgrade_bool).
      1) same version
      2) explicit '(recommended)' → 'upgrade obligatory'
      3) DF → 'critical upgrade suggested'
      4) MD/GD → 'upgrade suggested'
      5) otherwise → 'upgrade optional'
    """
    if not latest or not current:
        return None, None

    cur = normalize_version_by_platform(current.strip(), platform)
    lat = normalize_version_by_platform(latest.strip(), platform)

    if cur == lat:
        return "same version", False
    if is_explicit_rec:
        return "upgrade obligatory", True
    if designation == "DF":
        return "critical upgrade suggested", True
    if designation in {"MD", "GD"}:
        return "upgrade suggested", True
    return "upgrade optional", False

def backoff_sleep(attempt: int, base: float = BACKOFF_BASE_SEC):
    delay = min(base ** attempt, 30.0)
    time.sleep(delay)

def get_url_with_retry(model_name: str) -> Optional[str]:
    for attempt in range(1, MAX_RETRIES_URL + 1):
        url = extract_url_for_model(model_name)
        if url:
            return url
        logging.warning(f"[retry url] attempt {attempt}/{MAX_RETRIES_URL} failed for model '{model_name}'")
        if attempt < MAX_RETRIES_URL:
            backoff_sleep(attempt)
    return None

def scrape_with_retry(url: str) -> Optional[dict]:
    for attempt in range(1, MAX_RETRIES_SCRAPE + 1):
        info = scrape_latest_version(url)
        if info:
            return info
        logging.warning(f"[retry scrape] attempt {attempt}/{MAX_RETRIES_SCRAPE} failed for url '{url}'")
        if attempt < MAX_RETRIES_SCRAPE:
            backoff_sleep(attempt)
    return None

def main():
    logging.info("=== Starting pipeline ===")

    devices_map = load_json(DEVICES_JSON, {})          # dict keyed by hostname
    pid_alias   = load_json(PID_ALIAS_JSON, {})
    out_list    = load_json(OUT_JSON, [])

    if not isinstance(devices_map, dict):
        logging.error(f"{DEVICES_JSON} must be a JSON object keyed by hostname.")
        sys.exit(1)
    if not isinstance(pid_alias, dict):
        logging.error(f"{PID_ALIAS_JSON} must be a JSON object mapping PID -> model name.")
        sys.exit(1)
    if not isinstance(out_list, list):
        logging.error(f"{OUT_JSON} must be a JSON list (append-only).")
        sys.exit(1)

    appended = 0
    # Prefer externally provided batch timestamp (RUN_TS) so snapshots can correlate
    env_ts = os.getenv('RUN_TS')
    if env_ts:
        now_iso = env_ts
    else:
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    for host, dev in devices_map.items():
        pid       = (dev.get("model") or "").strip()
        platform  = (dev.get("platform") or "").strip() or None
        current   = (dev.get("version") or "").strip()
        eol_details = dev.get('eol_details') or {}
        # Extract new EoL fields (populated earlier by eol_details.py in orchestrator)
        eos_date   = eol_details.get('end_of_sale_date')
        eosup_date = eol_details.get('end_of_support_date')
        series_rel = eol_details.get('series_release_date')
        status_txt = eol_details.get('status')
        if not pid:
            logging.warning(f"Host {host}: 'model' (PID) missing, skipping.")
            out_list.append({
                "host": host, "pid": None, "switch_name": None,
                "platform": platform, "current_version": current or None,
                "recommended_version": None, "release_designation": None,
                "explicit_recommendation": None, "recommendation": "missing pid",
                "upgrade_recommended": None, "final_url": None,
                "selected_label": None, "screenshot_file": None,
                "checked_at": now_iso, "notes": "device missing PID (model)",
                # EoL details mirrored into upgrade-suggestions for batch-level access
                "end_of_sale_date": eos_date,
                "end_of_support_date": eosup_date,
                "series_release_date": series_rel,
                "status": status_txt,
            })
            appended += 1
            continue

        logging.info(f"Processing host={host} pid={pid} platform={platform or 'n/a'} current={current or 'n/a'}")

        model_name = pid_alias.get(pid)
        if not model_name:
            logging.warning(f"Host {host}: No alias for PID {pid}.")
            out_list.append({
                "host": host, "pid": pid, "switch_name": None,
                "platform": platform, "current_version": current or None,
                "recommended_version": None, "release_designation": None,
                "explicit_recommendation": None, "recommendation": "missing alias",
                "upgrade_recommended": None, "final_url": None,
                "selected_label": None, "screenshot_file": None,
                "checked_at": now_iso, "notes": "missing alias",
                "end_of_sale_date": eos_date,
                "end_of_support_date": eosup_date,
                "series_release_date": series_rel,
                "status": status_txt,
            })
            appended += 1
            continue

        # 1) Resolve URL using headless extractor from test01.py
        url = get_url_with_retry(model_name)
        if not url:
            logging.error(f"Host {host}: Could not get URL for model {model_name}")
            out_list.append({
                "host": host, "pid": pid, "switch_name": model_name,
                "platform": platform, "current_version": current or None,
                "recommended_version": None, "release_designation": None,
                "explicit_recommendation": None, "recommendation": "no url",
                "upgrade_recommended": None, "final_url": None,
                "selected_label": None, "screenshot_file": None,
                "checked_at": now_iso, "notes": "no url",
                "end_of_sale_date": eos_date,
                "end_of_support_date": eosup_date,
                "series_release_date": series_rel,
                "status": status_txt,
            })
            appended += 1
            continue

        # 2) Scrape latest version using headless scraper from test02.py
        info = scrape_with_retry(url)
        if not info:
            logging.error(f"Host {host}: Scrape failed for model {model_name}")
            out_list.append({
                "host": host, "pid": pid, "switch_name": model_name,
                "platform": platform, "current_version": current or None,
                "recommended_version": None, "release_designation": None,
                "explicit_recommendation": None, "recommendation": "scrape failed",
                "upgrade_recommended": None, "final_url": url,
                "selected_label": None, "screenshot_file": None,
                "checked_at": now_iso, "notes": "scrape failed",
                "end_of_sale_date": eos_date,
                "end_of_support_date": eosup_date,
                "series_release_date": series_rel,
                "status": status_txt,
            })
            appended += 1
            continue

        raw_latest = (info.get("latest_version") or "").strip()
        clean_latest, is_explicit_rec, designation = parse_version_meta(raw_latest)
        logging.info(f"Host {host}: scraped='{raw_latest}' → clean='{clean_latest}', explicit={is_explicit_rec}, desig={designation}")

        rec_text, rec_bool = decide_recommendation(current, clean_latest, is_explicit_rec, designation, platform)
        logging.info(f"Host {host}: recommendation='{rec_text}' upgrade={rec_bool}")

        out_list.append({
            "host": host,
            "pid": pid,
            "switch_name": model_name,
            "platform": platform,
            "current_version": current or None,
            "recommended_version": clean_latest or None,
            "release_designation": designation,
            "explicit_recommendation": is_explicit_rec,
            "recommendation": rec_text,
            "upgrade_recommended": rec_bool,
            "final_url": info.get("final_url") or url,
            "selected_label": info.get("selected_label"),
            "screenshot_file": info.get("screenshot_file"),
            "checked_at": now_iso,
            "scraped_version_raw": raw_latest or None,
            # EoL details mirrored into upgrade-suggestions for batch-level access
            "end_of_sale_date": eos_date,
            "end_of_support_date": eosup_date,
            "series_release_date": series_rel,
            "status": status_txt,
            "alias_used": model_name,
        })
        appended += 1

        # gentle pacing to reduce CDN suspicion
        time.sleep(1.0)

    if appended:
        save_json(OUT_JSON, out_list)
        logging.info(f"Appended {appended} new entries to {OUT_JSON}. Total entries: {len(out_list)}")
    else:
        logging.info("No new entries appended.")

    logging.info("=== Pipeline finished ===")

if __name__ == "__main__":
    main()
