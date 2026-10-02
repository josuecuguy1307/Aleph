# puppet-ai-core backend

Minimal FastAPI core for Puppet AI. No DB, no auth — entry point for the platform.

## Run

```bash
cd product/backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Test

```bash
cd product/backend
PYTHONPATH=. .venv/bin/python -m pytest tests/ -v
```
