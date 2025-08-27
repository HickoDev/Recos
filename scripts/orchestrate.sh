#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ANSIBLE_DIR="$ROOT_DIR/ansible"
DATA_DIR="$ROOT_DIR/data"
PIPELINE_DIR="$ROOT_DIR/pipeline"
MAIL_DIR="$ROOT_DIR/mail"
SCRAPING_DIR="$ROOT_DIR/scraping"

# One timestamp to correlate entire batch
export RUN_TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "[orchestrate] RUN_TS=$RUN_TS"

echo "=== Running IOS playbook ==="
ansible-playbook -i "$ANSIBLE_DIR/inventory.ini" "$ANSIBLE_DIR/get_ios_info.yml"

echo "=== Running NXOS playbook ==="
ansible-playbook -i "$ANSIBLE_DIR/inventory.ini" "$ANSIBLE_DIR/get_nxos_info.yml"

echo "=== Running CVEs check ==="
python3 "$PIPELINE_DIR/check_cves_from_devices.py"

echo "=== Checking end of life status ==="
python3 "$SCRAPING_DIR/eol_details.py" --batch --write --only-missing

echo "=== Running scraping pipeline (recommended versions) ==="
python3 "$PIPELINE_DIR/run_pipeline.py"

echo "=== CVE result ==="
cat "$DATA_DIR/device_cve_check.json" || true

echo "=== Final devices.json ==="
cat "$DATA_DIR/devices.json" || true

echo "=== Mail Notification ==="
python3 "$MAIL_DIR/emailtest.py" || true

echo "=== Writing history snapshots ==="
python3 "$PIPELINE_DIR/history_writer.py" || true

echo "=== Done ==="
