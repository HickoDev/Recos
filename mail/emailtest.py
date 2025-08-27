#!/usr/bin/env python3
import os, json, smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from dotenv import load_dotenv

load_dotenv()

SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
MAIL_FROM = os.getenv("MAIL_FROM")
MAIL_TO = os.getenv("MAIL_TO", "ali.dridi@insat.ucar.tn").split(",")

# ===== Paths & Files =====
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data')
SUGG_FILE = os.path.join(DATA_DIR, "upgrade-suggestions.json")   # append-only list
CVES_FILE = os.path.join(DATA_DIR, "device_cve_check.json")      # dict keyed by host
RAW_EMAIL_LAST = os.path.join(DATA_DIR, "email_last.eml")        # always overwritten

# Optional RUN_TS (exported by orchestrator) for stable batch identity
RUN_TS = os.getenv("RUN_TS")  # may be None if script run standalone

def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def parse_iso(s: str) -> datetime:
    # supports "2025-08-19T11:24:52Z" or with offset
    if s.endswith("Z"):
        s = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s)

def find_latest_batch(suggestions: list[dict]) -> tuple[str, list[dict]]:
    """Return (checked_at, entries_with_that_checked_at)."""
    if not suggestions:
        return "", []
    # get max checked_at
    timestamps = []
    for e in suggestions:
        ca = e.get("checked_at")
        if ca:
            try:
                timestamps.append(parse_iso(ca))
            except Exception:
                pass
    if not timestamps:
        return "", []
    latest_dt = max(timestamps)
    latest_iso = latest_dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    batch = [e for e in suggestions if e.get("checked_at") and
             parse_iso(e["checked_at"]) == latest_dt]
    return latest_iso, batch

def build_cve_index(cve_data: dict) -> dict:
    """Return {host: {"Critical": int, "High": int, "Medium": int, "Low": int}}"""
    out = {}
    for host, rec in (cve_data or {}).items():
        sev = rec.get("cves", {}) if isinstance(rec, dict) else {}
        out[host] = {
            "Critical": len(sev.get("Critical", [])) if isinstance(sev, dict) else 0,
            "High":     len(sev.get("High", []))     if isinstance(sev, dict) else 0,
            "Medium":   len(sev.get("Medium", []))   if isinstance(sev, dict) else 0,
            "Low":      len(sev.get("Low", []))      if isinstance(sev, dict) else 0,
        }
    return out

def format_email_body(latest_iso: str , batch: list[dict], cve_idx: dict) -> str:
    total = len(batch)
    crit_devices = 0
    rec_counts = {}
    lines = []
    lines.append(f"Latest upgrade suggestion batch: {latest_iso}")
    lines.append(f"Devices in this batch: {total}")
    lines.append("")

    # sort: Critical CVEs first, then by recommendation severity
    def sort_key(e):
        host = e.get("host")
        crit = cve_idx.get(host, {}).get("Critical", 0)
        rec  = (e.get("recommendation") or "").lower()
        rank = {"upgrade obligatory":0, "critical upgrade suggested":1,
                "upgrade suggested":2, "upgrade optional":3, "same version":4}.get(rec, 5)
        return (-crit, rank, e.get("host",""))

    batch_sorted = sorted(batch, key=sort_key)

    lines.append("Per-device details (latest run):")
    for e in batch_sorted:
        host = e.get("host")
        pid  = e.get("pid")
        plat = e.get("platform")
        cur  = e.get("current_version")
        recv = e.get("recommended_version")
        rec  = e.get("recommendation")
        url  = e.get("final_url")
        crit = cve_idx.get(host, {}).get("Critical", 0)
        high = cve_idx.get(host, {}).get("High", 0)
        med  = cve_idx.get(host, {}).get("Medium", 0)
        low  = cve_idx.get(host, {}).get("Low", 0)

        if crit > 0:
            crit_devices += 1

        rec_counts[rec] = rec_counts.get(rec, 0) + 1

        badge = "🔥 CRITICAL" if crit > 0 else ""
        lines.append(f"- {host} [{plat}] PID={pid}")
        lines.append(f"    Version: {cur}  →  {recv}   |  Recommendation: {rec} {badge}")
        lines.append(f"    CVEs: Critical={crit}, High={high}, Medium={med}, Low={low}")
        if url:
            lines.append(f"    Ref: {url}")
        lines.append("")

    lines.append("Summary:")
    lines.append(f"  Devices with Critical CVEs: {crit_devices}")
    for k,v in sorted(rec_counts.items(), key=lambda x:(-x[1],x[0])):
        lines.append(f"  {k}: {v}")

    return "\n".join(lines)

def send_notification():
    suggestions = load_json(SUGG_FILE, [])
    cves = load_json(CVES_FILE, {})

    latest_iso, batch = find_latest_batch(suggestions)
    if not batch:
        print("No latest batch found in upgrade-suggestions.json; nothing to notify.")
        return

    cve_idx = build_cve_index(cves)
    body = format_email_body(latest_iso, batch, cve_idx)

    # Prefer RUN_TS for subject/batch identity when present
    subject_ts = RUN_TS or latest_iso

    msg = EmailMessage()
    msg["Subject"] = f"[retrievos] Upgrade suggestions (batch {subject_ts})"
    msg["From"] = MAIL_FROM
    msg["To"] = ", ".join(MAIL_TO)
    msg.set_content("Hi,\n\n" + body + "\n\n— retrievos bot\n")
    # Save raw email before sending (so even if send fails we retain content)
    try:
        with open(RAW_EMAIL_LAST, "w", encoding="utf-8") as f:
            f.write(msg.as_string())
    except Exception as e:
        print(f"[email] Warning: could not write {RAW_EMAIL_LAST}: {e}")

    # Also write a batch-stamped copy if RUN_TS known
    if subject_ts:
        stamped = os.path.join(DATA_DIR, f"email_{subject_ts}.eml")
        try:
            with open(stamped, "w", encoding="utf-8") as f:
                f.write(msg.as_string())
        except Exception as e:
            print(f"[email] Warning: could not write {stamped}: {e}")

    # send (best-effort)
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        print(f"✅ Notification sent to {', '.join(MAIL_TO)} for batch {subject_ts} ({len(batch)} devices)")
    except Exception as e:
        print(f"[email] ERROR sending mail: {e}")

if __name__ == "__main__":
    send_notification()
