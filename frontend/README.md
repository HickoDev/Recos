# retrievos Vue 3 + Vite frontend

Dev server (requires Node.js 18+):

```bash
# using nvm (recommended if node is missing)
curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
export NVM_DIR="$HOME/.nvm"
. "$NVM_DIR/nvm.sh"
nvm install --lts

cd frontend
npm install
npm run dev
```

This starts Vite on http://localhost:5173 with a proxy to FastAPI at http://localhost:8000.

Production build:

```bash
cd frontend
npm install
npm run build
```

The output goes to `frontend/dist`. FastAPI is already configured to prefer serving `dist/index.html` at `/` and also mounted at `/app`.

Revert to the old static UI:

```bash
cd /home/g800996/retrievos
# pick the exact filename you saw when backup was created
tar -xzf backup_pre_vue_YYYYMMDDTHHMMSSZ.tgz -C .
# This restores dashboard/static and dashboard/main.py
```
