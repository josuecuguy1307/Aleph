"""test_advisor.py — GATE ADVISOR (ticket 5): clasificación de consecuencia por tool.

Cubre la doctrina completa: piso de plata (informa, no sugiere) · envío · escritura ·
EXFIL (lectura con canal saliente parametrizable — el hueco que el runtime no ve) ·
lectura obvia (no consecuente) · AMBIGUA fail-closed · copy bilingüe · endpoint batch
con dedup. Espejo del runtime: lo que el enforcer frena, el advisor lo hace visible.
"""
from fastapi.testclient import TestClient

from app.main import app
from app.phase1.advisor import classify_tool

client = TestClient(app)


# ── clasificación pura ─────────────────────────────────────────────────────────

def test_plata_es_piso_no_sugerencia():
    r = classify_tool("transfer_funds")
    assert r["clase"] == "plata" and r["consecuente"] and r["piso_server"]
    assert not r["sugerir_gate"]          # el piso ya existe server-side: se informa
    r2 = classify_tool("pagar_factura")
    assert r2["clase"] == "plata" and r2["piso_server"]


def test_envio_sugiere_gate():
    for t in ("send_mail", "post_message", "publicar_tweet", "notify_channel"):
        r = classify_tool(t)
        assert r["consecuente"] and r["sugerir_gate"], t
        assert r["clase"] in ("envio", "escritura"), t   # post/publish caen en cualquiera de los espejos


def test_escritura_externa_sugiere_gate():
    for t in ("create_issue", "delete_row", "update_record", "borrar_archivo"):
        r = classify_tool(t)
        assert r["clase"] == "escritura" and r["consecuente"] and r["sugerir_gate"], t


def test_exfil_lectura_con_canal_saliente():
    # LECTURAS para el runtime (auto-ejecutan) pero con canal saliente parametrizable:
    # el advisor las marca consecuentes — este es el corazón del ticket 5.
    for t in ("search_web", "fetch_url", "query_external_api", "browse_page", "buscar_noticias"):
        r = classify_tool(t)
        assert r["clase"] == "exfil", (t, r["clase"])
        assert r["consecuente"] and r["sugerir_gate"], t
    assert "cuenta" in classify_tool("search_web")["why"]["es"]   # microcopy menciona el riesgo de datos de cuenta


def test_lectura_obvia_no_consecuente():
    for t in ("get_price", "list_files", "read_document", "ver_estado", "count_rows"):
        r = classify_tool(t)
        assert r["clase"] == "lectura" and not r["consecuente"] and not r["sugerir_gate"], t


def test_ambigua_fail_closed():
    for t in ("frobnicate", "hacer_magia", "process2", ""):
        r = classify_tool(t)
        assert r["clase"] == "ambigua" and r["consecuente"] and r["sugerir_gate"], t


def test_evasivas_no_pasan_por_lectura():
    # nombre con token de lectura PERO con envío adentro → jamás "lectura" (espejo del gate)
    r = classify_tool("get_and_send_report")
    assert r["consecuente"] and r["sugerir_gate"]
    # "account" NO contiene el token "count" (match por token, no substring)
    r2 = classify_tool("fund_account")
    assert r2["clase"] == "plata" and r2["piso_server"]


def test_why_bilingue():
    r = classify_tool("search_web")
    assert r["why"]["es"] and r["why"]["en"] and r["why"]["code"] == "exfil"


# ── endpoint ───────────────────────────────────────────────────────────────────

def test_endpoint_batch_dedup_y_resumen():
    body = {"tools": ["send_mail", "get_price", "send_mail", "frobnicate", "transfer_funds"]}
    resp = client.post("/v1/advisor/classify", json=body)
    assert resp.status_code == 200
    d = resp.json()
    names = [t["tool"] for t in d["tools"]]
    assert names == ["send_mail", "get_price", "frobnicate", "transfer_funds"]   # dedup, orden estable
    assert d["resumen"]["total"] == 4
    assert d["resumen"]["consecuentes"] == 3
    assert d["resumen"]["sugeridos"] == 2        # send_mail + frobnicate (la plata es piso, no sugerencia)
    assert d["resumen"]["piso_server"] == 1


def test_endpoint_body_invalido_422():
    assert client.post("/v1/advisor/classify", json={}).status_code == 422
    assert client.post("/v1/advisor/classify", json={"tools": "no-lista"}).status_code == 422
