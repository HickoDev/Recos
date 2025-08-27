# retrievos — Cisco device dashboard (FastAPI + Vue)

This project provides a small dashboard to review historical Cisco device data and run a pipeline that:
- Collects device info (Ansible IOS/NXOS, optional)
- Checks CVEs against current versions
- Checks End-of-Life status
- Scrapes Cisco site for recommended versions
- Writes history snapshots and optionally emails a notification

The backend is FastAPI (Python). The frontend is Vue 3 + Vite. In dev you can run the Vite server with proxy; in build mode FastAPI serves `frontend/dist` at `/`.

## Quick start (new VM)

These steps assume Ubuntu/Debian. Adapt package manager commands for other distros.

### 1) System prerequisites

```bash
# Core tools
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip build-essential libffi-dev libssl-dev unzip jq

# Browser for scraping (pick one)
# Option A: Google Chrome (if you have the .deb handy in project root)
sudo apt install -y ./google-chrome-stable_current_amd64.deb || true
# Option B: Chromium from apt
sudo apt install -y chromium-browser || sudo apt install -y chromium
```

### 2) Clone and set up Python venv

```bash
git clone <your-fork-or-repo-url> retrievos
cd retrievos
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 3) Configure environment

Create a `.env` file in the repository root (see `.env.example`). This is required for Cisco API, SMTP email notifications, and dashboard login.

```bash
cp .env.example .env
# Then edit .env and fill in values
```

Required variables:
- CISCO_CLIENT_ID, CISCO_CLIENT_SECRET: Cisco API credentials
- SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS: Mail relay (e.g., Gmail with an app password)
- MAIL_FROM, MAIL_TO: Sender and recipient for pipeline notifications
- SECRET_KEY: Random string to sign session cookies (set to a long random value)
- ADMIN_USER, ADMIN_PASSWORD: Credentials for dashboard login (POST /api/auth/login)

> Tip: Keep your real secrets out of version control. The `.env` file is git-ignored.

### 4) Build the frontend (once)

Node.js 18+ is recommended. If Node isn’t installed, use nvm:

```bash
# Install nvm if needed
curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
export NVM_DIR="$HOME/.nvm"
. "$NVM_DIR/nvm.sh"
nvm install --lts

# Build the Vue app
cd frontend
npm install
npm run build
cd ..
```

FastAPI will serve `frontend/dist` at `/` automatically when you run the backend.

### 5) Run the backend (serve built frontend)

```bash
# From repo root, with the venv active
source .venv/bin/activate
python -m uvicorn dashboard.main:app --host 0.0.0.0 --port 8000 --reload
```

Open the dashboard at:
- http://localhost:8000/
- or http://<vm-ip>:8000/

Authentication:
- The dashboard requires login for actions that modify state (start pipeline, edit inventory). If `ADMIN_PASSWORD` is empty, authentication is disabled (open mode) for convenience on dev VMs.
- Endpoints: POST `/api/auth/login` with `{ "username": "<ADMIN_USER>", "password": "<ADMIN_PASSWORD>" }` to create a session cookie; POST `/api/auth/logout` to end the session; GET `/api/auth/me` to check current session.
- Configure `ADMIN_USER`, `ADMIN_PASSWORD`, and `SECRET_KEY` in `.env`. For production, prefer setting `ADMIN_PASSWORD` as a PBKDF2 hash (see `.env.example`).

Alternative (dev mode with hot reload): see "Development mode" below for running the Vite dev server at http://localhost:5173/.

## Using the dashboard

- Batches dropdown: browse historical snapshots from `data/history/*`.
- Devices table:
  - Shows version info, recommendation, CVE counts, and EoL details.
  - EoL columns: Status, Series Release, End-of-Sale, End-of-Support.
  - Status color coding: green=Available/Active, yellow=End-of-Sale, red=End-of-Support.
  - Click a Designation badge (e.g., DF/MD/GD) to see a small explanation modal.
- Control panel:
  - PID aliases: add/check/list product ID aliases used by scraping.
  - Run mode: choose `full` (with Ansible) or `no-ansible` (uses current `data/devices.json`).
  - Start pipeline: launches the orchestrator and streams a live log tail with progress.
- Inventory: manage Ansible inventory (groups ios/nxos) from the UI.

When a run completes, the spinner stops and a green “Completed” chip appears. Click “Refresh status” to return the panel to the idle state (keeps the last run timestamp).

## Pipeline runs

- From the UI: select a mode and click “Start pipeline”.
- From the CLI:

```bash
curl -X POST http://localhost:8000/api/run \
  -H 'Content-Type: application/json' \
  -d '{"mode":"no-ansible"}'

# Poll status
curl -s http://localhost:8000/api/run/status | jq .
```

Artifacts:
- Live log: `data/orchestrate_current.log`
- History logs: `data/history/logs/run_pipeline_<ts>.log`
- History snapshots: `data/history/*_snapshot.jsonl`
- Emails: `data/history/mails/notification_<ts>.eml` (also sent via SMTP)

Pipeline internals (what happens when you run):
- Orchestrators (`scripts/orchestrate*.sh`) set a batch timestamp `RUN_TS` and execute steps.
- CVEs: `pipeline/check_cves_from_devices.py` updates `data/device_cve_check.json`.
- EoL details: the orchestrator calls `scraping/eol_details.py --batch --write --only-missing`.
  - Writes `eol_details` into each device in `data/devices.json` (end_of_sale_date, end_of_support_date, series_release_date, status + navigation meta).
- Recommended versions: `pipeline/run_pipeline.py` writes `data/upgrade-suggestions.json`.
  - Mirrors EoL fields into each entry so batch snapshots can reference them.
- History snapshots: `pipeline/history_writer.py` writes JSONL rows for devices/CVEs and a batch summary under `data/history/`.
  - Snapshot rows include the EoL fields used in the dashboard.

## Ansible setup (for full mode)

Edit `ansible/inventory.ini` with your device hosts and credentials. Example:

```ini
[ios]
switch1 ansible_host=192.168.30.10 ansible_user=USER ansible_password=PASS ansible_network_os=cisco.ios.ios ansible_connection=network_cli

[nxos]
nxos1 ansible_host=example-nxos.cisco.com ansible_user=USER ansible_password=PASS ansible_network_os=cisco.nxos.nxos ansible_connection=network_cli
```

Install required Ansible collections:

```bash
ansible-galaxy collection install cisco.ios cisco.nxos
```

Notes:
- Ensure network reachability and authorization to collect show commands.
- The playbooks update `data/devices.json`. The pipeline consumes this file.

If you prefer to skip Ansible, choose `no-ansible` mode—the pipeline uses the current `data/devices.json` content.

## Development mode (optional)

Run the Vite dev server with proxy to FastAPI:

```bash
# Terminal 1: backend
source .venv/bin/activate
python -m uvicorn dashboard.main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2: frontend
cd frontend
npm install
npm run dev
```

Open http://localhost:5173/ for hot-reload development. API requests are proxied to http://localhost:8000/.

VS Code tasks: the repo includes `.vscode/tasks.json` pointing to a specific venv path (`/home/g800996/ansible-env`). On a different VM, either update that path or run uvicorn manually as shown above.

API overview (for integrations and debugging):
- GET `/api/batches` → list batch timestamps
- GET `/api/batch/{ts}/devices` → device rows for a batch (includes EoL fields)
- GET `/api/batch/{ts}/cves` → CVE rows for a batch
- GET `/api/device/{host}/timeline` → condensed timeline for one device
- GET `/api/latest` → devices for the most recent batch
- GET `/api/batch/{ts}/log` → pipeline log text
- GET `/api/batch/{ts}/mail` → saved notification email
- GET/POST `/api/pid_alias` and `/api/pid_alias/{pid}` → PID alias management
- GET/POST/DELETE `/api/inventory` endpoints → inventory management
  - Note: POST/DELETE inventory endpoints and POST `/api/run` require an authenticated session.

## Troubleshooting

- Browser/driver issues during scraping:
  - Install Chrome or Chromium on the VM.
  - Ensure the user running the app can launch a browser (Xvfb may be needed on headless servers; undetected-chromedriver typically manages the driver automatically).
- Email sending fails:
  - Verify `.env` SMTP settings and that the mail provider allows SMTP (for Gmail, use an app password).
- 422 Unprocessable Entity on `/api/run`:
  - Ensure you POST JSON with header `Content-Type: application/json` and body like `{"mode":"no-ansible"}`.
- 500 orchestrate script not found:
  - Verify the scripts exist: `scripts/orchestrate.sh` and `scripts/orchestrate_no_ansible.sh`.
- Permission errors writing to `data/`:
  - Ensure the app user has write permissions in `data/`.
- Status column not colored / EoL fields empty:
  - Run a new pipeline (no-ansible is fine). The EoL scraper runs in batch mode and writes fields; refresh the dashboard after completion.

## Security

- Do not commit `.env` with real secrets. Use `.env.example` to share the shape of required variables.
- Review access to your Ansible credentials and inventory.

## Ports

- 8000: FastAPI server
- 5173: Vite dev server (optional)

## License

This project includes third-party dependencies. Review their licenses as needed.
