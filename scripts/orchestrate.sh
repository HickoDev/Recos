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

# Prepare a temporary decrypted inventory for Ansible if values are encrypted
TMP_INV="$ANSIBLE_DIR/inventory.decrypted.ini"
if python3 -c 'import sys,re; s=open(sys.argv[1]).read(); sys.exit(0 if re.search(r"ansible_password=enc\$", s) else 1)' "$ANSIBLE_DIR/inventory.ini"; then
	echo "[orchestrate] Decrypting inventory passwords -> $TMP_INV"
	ROOT_DIR="$ROOT_DIR" python3 - <<-'PY'
	import os, importlib.util
	root = os.environ.get('ROOT_DIR') or os.getcwd()
	mod_path = os.path.join(root, 'ansible', 'inventory_crypto.py')
	spec = importlib.util.spec_from_file_location('inventory_crypto_local', mod_path)
	mod = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(mod)  # type: ignore
	inv = os.path.join(root, 'ansible', 'inventory.ini')
	out = os.path.join(root, 'ansible', 'inventory.decrypted.ini')
	txt = open(inv, 'r', encoding='utf-8').read()
	dec = mod.decrypt_inventory_text(txt)
	open(out, 'w', encoding='utf-8').write(dec)
	print('[decrypt] inventory written:', out)
PY
	INV_PATH="$TMP_INV"
else
	INV_PATH="$ANSIBLE_DIR/inventory.ini"
fi

echo "=== Running IOS playbook ==="
ansible-playbook -i "$INV_PATH" "$ANSIBLE_DIR/get_ios_info.yml"

echo "=== Running NXOS playbook ==="
ansible-playbook -i "$INV_PATH" "$ANSIBLE_DIR/get_nxos_info.yml"

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

# Cleanup tmp inventory
rm -f "$TMP_INV" 2>/dev/null || true
