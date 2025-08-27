import json
import requests
import os
import re
from dotenv import load_dotenv

# Adjust working directory awareness so script can be run from repo root or pipeline/
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data')
DEVICES_JSON = os.path.join(DATA_DIR, 'devices.json')
OUTPUT_JSON = os.path.join(DATA_DIR, 'device_cve_check.json')

load_dotenv()

CLIENT_ID = os.getenv("CISCO_CLIENT_ID")
CLIENT_SECRET = os.getenv("CISCO_CLIENT_SECRET")

TOKEN_URL = "https://id.cisco.com/oauth2/default/v1/token"
ADVISORY_URL = "https://apix.cisco.com/security/advisories/v2/OSType"

# --- Version normalization (mirror of pipeline) ---
RE_IOS_PAREN = re.compile(r"^(\d+)\.(\d+)\((\d+)\)([A-Za-z]+)?(\d+)?$")
RE_IOS_DASH = re.compile(r"^(\d+)\.(\d+)\.(\d+)-([A-Za-z]+)(\d+)$")
RE_IOS_DASH_SHORT = re.compile(r"^(\d+)\.(\d+)\.(\d+)([A-Za-z]+)(\d+)$")

def to_ios_canonical(v: str) -> str:
    s = (v or '').strip()
    if not s:
        return s
    m = RE_IOS_PAREN.match(s)
    if m:
        return s
    m = RE_IOS_DASH.match(s)
    if m:
        a,b,c,sfx,n = m.groups(); return f"{a}.{b}({c}){sfx}{n}"
    m = RE_IOS_DASH_SHORT.match(s)
    if m:
        a,b,c,sfx,n = m.groups(); return f"{a}.{b}({c}){sfx}{n}"
    return s

def version_variants(platform: str, v: str):
    p = (platform or '').lower()
    s = (v or '').strip()
    if not s:
        return []
    if p in ('ios','iosxe','ios-xe'):
        # generate a few reasonable variants to improve match rate
        out = []
        can = to_ios_canonical(s)
        out.append(can)
        m = RE_IOS_PAREN.match(can)
        if m:
            a,b,c,sfx,n = m.groups()
            if sfx and n:
                out.append(f"{a}.{b}.{c}-{sfx}{n}")  # 15.0.2-SE11
                out.append(f"{a}.{b}.{c}{sfx}{n}")   # 15.0.2SE11
        if s not in out:
            out.append(s)
        return out
    return [s]

# 1. Get Token
def get_token():
    data = {
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    r = requests.post(TOKEN_URL, data=data, headers=headers)
    r.raise_for_status()
    return r.json()["access_token"]

# 2. Get advisories for platform + version
def get_advisories(token, platform, version):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    }
    url = f"{ADVISORY_URL}/{platform}"
    # Try canonical and alternative variants for better match
    for ver in version_variants(platform, version):
        params = {"version": ver}
        r = requests.get(url, headers=headers, params=params)
        if r.status_code == 200:
            adv = r.json().get("advisories", [])
            if adv:
                return adv
        # Continue trying other variants on failure or empty result
    # Final attempt with original version
    r = requests.get(url, headers=headers, params={"version": version})
    if r.status_code != 200:
        print(f"⚠️ Error for {platform} {version}: {r.status_code}")
        return []
    return r.json().get("advisories", [])

# 3. Organize CVEs by severity
def organize_by_severity(advisories):
    """Group CVEs by severity; include useful links.

    Each entry will contain:
      - id: CVE identifier
      - title: Cisco advisory title
      - advisory_id: Cisco advisory ID (if available)
      - cisco_url: direct link to Cisco advisory or a Cisco search fallback
      - nvd_url: link to NVD CVE page
    """
    result = {"Critical": [], "High": [], "Medium": [], "Low": []}
    for adv in advisories or []:
        severity = adv.get("sir", "Unknown")
        title = adv.get("advisoryTitle", "No title")
        advisory_id = adv.get("advisoryId") or adv.get("advisoryIdentifier")
        # Build a Cisco advisory URL if we have an ID; otherwise fallback to Cisco Security search by CVE
        base_adv_url = (
            f"https://tools.cisco.com/security/center/content/CiscoSecurityAdvisory/{advisory_id}"
            if advisory_id else None
        )
        for cve in adv.get("cves", []) or []:
            cve_id = (cve or "").strip()
            nvd_url = f"https://nvd.nist.gov/vuln/detail/{cve_id}" if cve_id else None
            cisco_search = f"https://tools.cisco.com/security/center/search.x?search={cve_id}" if cve_id else None
            entry = {
                "id": cve_id,
                "title": title,
                "advisory_id": advisory_id,
                "cisco_url": base_adv_url or cisco_search,
                "nvd_url": nvd_url,
            }
            if severity in result:
                result[severity].append(entry)
            else:
                result.setdefault(severity, []).append(entry)
    return result
# 4. Main
def main():
    # Load devices.json
    with open(DEVICES_JSON) as f:
        devices = json.load(f)

    token = get_token()
    output = {}

    for name, device in devices.items():
        platform = device["platform"]
        version = device["version"]
        advisories = get_advisories(token, platform, version)
        output[name] = {
            "model": device["model"],
            "version": version,
            "cves": organize_by_severity(advisories)
        }
        print(f"✅ Checked {name} ({platform} {version})")

    # Save results
    with open(OUTPUT_JSON, "w") as f:
        json.dump(output, f, indent=4)

    print(f"📂 Results saved in {OUTPUT_JSON}")

if __name__ == "__main__":
    main()
