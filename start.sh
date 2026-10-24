#!/bin/zsh
set -e
cd "${0:A:h}"
if [[ ! -x .venv/bin/python ]]; then
    python3 -m venv .venv
fi
.venv/bin/python -m pip install -q -r requirements.txt
mkdir -p data
if ! lsof -nP -iTCP:8501 -sTCP:LISTEN >/dev/null 2>&1; then
    nohup .venv/bin/python -m streamlit run app.py --server.address 127.0.0.1 --server.headless true \
        --browser.gatherUsageStats false >data/server.log 2>data/server-error.log &
fi
echo 'Find My Dance is running in the background at http://127.0.0.1:8501/'
