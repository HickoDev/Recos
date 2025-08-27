#!/bin/bash
set -e

echo "=== Running IOS playbook ==="
ansible-playbook -i inventory.ini get_ios_info.yml

echo "=== Running NXOS playbook ==="
ansible-playbook -i inventory.ini get_nxos_info.yml



echo "=== Running  CVEs check ==="
python3 check_cves_from_devices.py
echo "=== checking end of life status"
python3 eolcheck.py 
echo "=== Running Python pipeline ( scrapping os recommended versions ) ==="
python3 run_pipeline.py


echo "=== CVE result ==="
cat device_cve_check.json
echo "=== Final devices.json ==="
cat devices.json


echo "=== Mail Notification ==="
python3 emailtest.py
