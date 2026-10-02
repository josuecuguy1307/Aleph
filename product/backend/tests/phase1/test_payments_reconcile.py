"""test_payments_reconcile.py — la red de seguridad · Step 5 · Casa 1 · P5.

Simula el escenario real que justifica el job: un webhook que NUNCA llegó (el server
estuvo caído más de las ~28 h de reintentos de Dodo). El estado local quedó viejo y
sólo la reconciliación puede arreglarlo.

El procesador se reemplaza por un doble que devuelve la "verdad remota" que le pidamos.
La DB es la real.
"""
from __future__ import annotations

import datetime as _dt
import sys
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
for p in (REPO_ROOT / "platform", REPO_ROOT / "product" / "backend"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

pytestmark = pytest.mark.db


def _pg():
    try:
        from app.phase1 import repo
        c = repo.get_conn()
        c.close()
        return True
    except Exception:
        return False


if not _pg():
    pytest.skip("Postgres puppet_ai no disponible", allow_module_level=True)

AHORA = _dt.datetime.now(_dt.timezone.utc)
FUTURO = AHORA + _dt.timedelta(days=30)
PASADO = AHORA - _dt.timedelta(days=30)


class _ProcDoble:
    """Devuelve la verdad remota que le configuremos, sin tocar la red."""

    nombre = "dodo"

    def __init__(self, verdades=None, revienta=False, desconoce=False):
        self.verdades = verdades or {}
        self.revienta = revienta
        self.desconoce = desconoce
        self.consultados = []

    def consultar_estado(self, external_id):
        self.consultados.append(external_id)
        if self.revienta:
            raise RuntimeError("la API del procesador se cayó")
        if self.desconoce:
            return None
        return self.verdades.get(external_id)


def _remoto(status, fin=None):
    """OJO: `status` es el VOCABULARIO PROPIO (alta/baja/en_gracia/…), no el string
    crudo del procesador. `consultar_estado` del adaptador real ya traduce — el doble
    tiene que imitar eso o el test miente. (Ver el test de más abajo: un estado sin
    traducir NO otorga premium, que es lo correcto pero no es lo que estos casos
    quieren probar.)"""
    from payments.base import EstadoRemoto
    return EstadoRemoto(external_id="x", status=status, current_period_end=fin)


@pytest.fixture()
def cuenta():
    from app.phase1 import repo
    conn = repo.get_conn()
    u = repo.get_or_create_user(conn, f"p5-{uuid.uuid4().hex[:8]}@probe.local", "Sonda P5")
    yield conn, u["id"]
    with conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE id = %s::uuid", (u["id"],))
    conn.commit()
    conn.close()


def _sembrar(conn, uid, ext, status, plan="monthly", fin=FUTURO):
    from app.phase1 import repo
    repo.upsert_subscription(
        conn, account_id=uid, processor="dodo", external_id=ext,
        plan=plan, status=status, current_period_end=fin,
        event_at=AHORA - _dt.timedelta(days=2))
    repo.resync_account_tier(conn, uid, reason="test:siembra")


# ── DIRECCIÓN 1 · el ASCENSO perdido (pagó y quedó en free) ────────────────────
def test_recupera_un_ascenso_cuyo_webhook_se_perdio(cuenta):
    """Pagó, el webhook nunca llegó, quedó en free. Sin esto, pierde el servicio
    que pagó y nosotros la confianza."""
    from app.phase1 import repo
    from payments import reconcile
    conn, uid = cuenta

    ext = f"sub_{uuid.uuid4().hex[:10]}"
    _sembrar(conn, uid, ext, "baja", fin=PASADO)          # local: vencida → free
    assert repo.get_user(conn, uid)["tier"] == "free"

    proc = _ProcDoble({ext: _remoto("alta", FUTURO)})     # remoto: está VIVA y paga
    res = reconcile.reconciliar(conn, proc, repo, solo_account_id=uid, ahora=AHORA)

    assert res["corregidas"] == 1
    assert res["tiers_cambiados"] == 1
    assert repo.get_user(conn, uid)["tier"] == "basico", \
        "no recuperó a un cliente que pagó y cuyo webhook se perdió"


# ── DIRECCIÓN 2 · la BAJA perdida (canceló y sigue premium gratis) ─────────────
def test_corrige_una_baja_cuyo_webhook_se_perdio(cuenta):
    from app.phase1 import repo
    from payments import reconcile
    conn, uid = cuenta

    ext = f"sub_{uuid.uuid4().hex[:10]}"
    _sembrar(conn, uid, ext, "alta", fin=FUTURO)          # local: premium
    assert repo.get_user(conn, uid)["tier"] == "basico"

    proc = _ProcDoble({ext: _remoto("baja", PASADO)})  # remoto: cancelada y vencida
    res = reconcile.reconciliar(conn, proc, repo, solo_account_id=uid, ahora=AHORA)

    assert res["corregidas"] == 1
    assert repo.get_user(conn, uid)["tier"] == "free", \
        "dejó a alguien premium gratis tras una baja cuyo webhook se perdió"


# ── Sin deriva, no toca nada ───────────────────────────────────────────────────
def test_sin_deriva_no_corrige_ni_audita(cuenta):
    from app.phase1 import repo
    from payments import reconcile
    conn, uid = cuenta

    ext = f"sub_{uuid.uuid4().hex[:10]}"
    _sembrar(conn, uid, ext, "alta", fin=FUTURO)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM tier_audit WHERE account_id = %s::uuid", (uid,))
        antes = cur.fetchone()[0]

    proc = _ProcDoble({ext: _remoto("alta", FUTURO)})
    res = reconcile.reconciliar(conn, proc, repo, solo_account_id=uid, ahora=AHORA)

    assert res["revisadas"] == 1 and res["corregidas"] == 0
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM tier_audit WHERE account_id = %s::uuid", (uid,))
        assert cur.fetchone()[0] == antes, "auditó un no-cambio"


# ── Robustez: la ambigüedad NO degrada a nadie ─────────────────────────────────
def test_si_el_procesador_no_reconoce_la_suscripcion_NO_degrada(cuenta):
    """Respuesta ambigua (corte de red, id de otro entorno, cambio de API). Degradar
    acá le cortaría el servicio a alguien que sí pagó."""
    from app.phase1 import repo
    from payments import reconcile
    conn, uid = cuenta

    ext = f"sub_{uuid.uuid4().hex[:10]}"
    _sembrar(conn, uid, ext, "alta", fin=FUTURO)
    assert repo.get_user(conn, uid)["tier"] == "basico"

    res = reconcile.reconciliar(conn, _ProcDoble(desconoce=True), repo, solo_account_id=uid, ahora=AHORA)

    assert res["errores"] == 1 and res["corregidas"] == 0
    assert repo.get_user(conn, uid)["tier"] == "basico", \
        "degradó a un cliente pago por una respuesta ambigua"


def test_una_suscripcion_rota_no_aborta_el_barrido(cuenta):
    """Un fallo aislado no puede congelar la reconciliación de todas las demás."""
    from app.phase1 import repo
    from payments import reconcile
    conn, uid = cuenta

    for i in range(3):
        _sembrar(conn, uid, f"sub_rota_{uuid.uuid4().hex[:8]}_{i}", "alta", fin=FUTURO)

    res = reconcile.reconciliar(conn, _ProcDoble(revienta=True), repo, solo_account_id=uid, ahora=AHORA)
    assert res["revisadas"] == 3, "abortó el barrido en la primera que falló"
    assert res["errores"] == 3
    assert repo.get_user(conn, uid)["tier"] == "basico"


# ── No gasta llamadas en lo terminal ───────────────────────────────────────────
def test_no_consulta_las_terminales(cuenta):
    from app.phase1 import repo
    from payments import reconcile
    conn, uid = cuenta

    ext_t = f"sub_term_{uuid.uuid4().hex[:8]}"
    ext_v = f"sub_viva_{uuid.uuid4().hex[:8]}"
    _sembrar(conn, uid, ext_t, "terminal", fin=None)
    _sembrar(conn, uid, ext_v, "alta", fin=FUTURO)

    proc = _ProcDoble({ext_v: _remoto("alta", FUTURO)})
    reconcile.reconciliar(conn, proc, repo, solo_account_id=uid, ahora=AHORA)

    assert ext_t not in proc.consultados, "gastó una llamada en una suscripción terminal"
    assert ext_v in proc.consultados


def test_la_baja_SI_se_revisa(cuenta):
    """`baja` no es terminal: se puede reactivar, y su período pagado sigue corriendo."""
    from app.phase1 import repo
    from payments import reconcile
    conn, uid = cuenta

    ext = f"sub_baja_{uuid.uuid4().hex[:8]}"
    _sembrar(conn, uid, ext, "baja", fin=PASADO)
    proc = _ProcDoble({ext: _remoto("alta", FUTURO)})
    reconcile.reconciliar(conn, proc, repo, solo_account_id=uid, ahora=AHORA)

    assert ext in proc.consultados, "no revisó una baja (que puede reactivarse)"
    assert repo.get_user(conn, uid)["tier"] == "basico"


# ── La corrección deja rastro con su motivo ────────────────────────────────────
def test_la_correccion_queda_auditada_como_reconciliacion(cuenta):
    from app.phase1 import repo
    from payments import reconcile
    conn, uid = cuenta

    ext = f"sub_{uuid.uuid4().hex[:10]}"
    _sembrar(conn, uid, ext, "baja", fin=PASADO)
    proc = _ProcDoble({ext: _remoto("alta", FUTURO)})
    reconcile.reconciliar(conn, proc, repo, solo_account_id=uid, ahora=AHORA)

    with conn.cursor() as cur:
        cur.execute("SELECT reason FROM tier_audit WHERE account_id = %s::uuid "
                    "ORDER BY at DESC LIMIT 1", (uid,))
        assert cur.fetchone()[0].startswith("reconciliation:")


# ── Fail-closed ante un adaptador que NO traduce ───────────────────────────────
def test_un_estado_sin_traducir_NO_otorga_premium(cuenta):
    """Si un adaptador (nuevo o roto) devolviera el string CRUDO del procesador en vez
    del vocabulario propio, la reconciliación NO puede ascender a nadie.

    Este test nació de un falso verde: el doble devolvía 'active'/'cancelled' (crudo de
    Dodo) y uno de los casos "pasaba" sólo porque el resultado esperado coincidía con el
    fail-closed. El sistema se comportó bien; el test mentía. Queda pineado para que un
    procesador que no traduzca falle en ROJO y no en silencio.
    """
    from app.phase1 import repo
    from payments import reconcile
    conn, uid = cuenta

    ext = f"sub_{uuid.uuid4().hex[:10]}"
    _sembrar(conn, uid, ext, "baja", fin=PASADO)
    assert repo.get_user(conn, uid)["tier"] == "free"

    # 'active' es el string de Dodo, NO nuestro vocabulario
    proc = _ProcDoble({ext: _remoto("active", FUTURO)})
    reconcile.reconciliar(conn, proc, repo, solo_account_id=uid, ahora=AHORA)

    assert repo.get_user(conn, uid)["tier"] == "free", \
        "un estado sin traducir ascendió a premium (fail-OPEN)"
