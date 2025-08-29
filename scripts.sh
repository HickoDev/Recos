#!/bin/bash
set -e

echo "=== Preparing inventory ==="
TMP_INV="ansible/inventory.decrypted.ini"
INV_SRC="ansible/inventory.ini"
if python3 -c 'import sys,re; s=open(sys.argv[1]).read(); sys.exit(0 if re.search(r"ansible_password=enc\$", s) else 1)' "$INV_SRC"; then
	echo "Decrypting inventory passwords -> $TMP_INV"
	ROOT_DIR="$(pwd)" python3 - <<-'PY'
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
print('inventory written:', out)
PY
	INV_PATH="$TMP_INV"
else
	INV_PATH="$INV_SRC"
fi

echo "=== Running IOS playbook ==="
ansible-playbook -i "$INV_PATH" ansible/get_ios_info.yml

echo "=== Running NXOS playbook ==="
ansible-playbook -i "$INV_PATH" ansible/get_nxos_info.yml



echo "=== Running  CVEs check ==="
python3 pipeline/check_cves_from_devices.py
echo "=== checking end of life status"
python3 pipeline/eolcheck.py 
echo "=== Running Python pipeline ( scrapping os recommended versions ) ==="
python3 pipeline/run_pipeline.py


echo "=== CVE result ==="
cat data/device_cve_check.json || true
echo "=== Final devices.json ==="
cat data/devices.json || true


echo "=== Mail Notification ==="
python3 mail/emailtest.py || true

rm -f "$TMP_INV" 2>/dev/null || true
