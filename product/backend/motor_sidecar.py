"""motor_sidecar — el runner DOCUMENTADO de verify_cuarto_semaforo_sidecar.mjs (T2 §3).

Sidecar mínimo que monta SOLO el Motor de Verdad real (build_motor_router, cero stubs)
+ /health {ok:true} (el contrato que espera el health-gate del verify). Vivía suelto en
el worktree de T2 sin commitear — T6 lo fija al repo para que la tanda sea reproducible.

Levantar:  PYTHONPATH=product/backend python -m uvicorn motor_sidecar:app --port 8188
Correr:    MOTOR_SIDECAR=http://127.0.0.1:8188 node .../verify_cuarto_semaforo_sidecar.mjs
"""
from fastapi import FastAPI

from app.phase1.motor_verdad import build_motor_router

app = FastAPI(title="motor-sidecar")
app.include_router(build_motor_router())


@app.get("/health")
def health():
    return {"ok": True, "service": "motor-sidecar"}
