#!/usr/bin/env python3
"""VARA · ELEGIR TU API EN EL PANEL DEJA UN AGENTE QUE CORRE.

EL BUG QUE CIERRA — `el-alias-byok-se-manda-como-modelo`.

`compileModel` (la rama BYOK de `cuarto.models.js`) ponía el modelo real del usuario en
`primary`… y además `alias: "byok"`. Pero `byok` es el id de la LANE CURADA, no un alias del
registro: `models.py` no lo tiene, y su docstring dice que es DECLARATIVO. Como
`resolve_recipe_model` aplica la precedencia sellada

    env PUPPET_BRAIN  >  model.alias  >  model.primary + model.base_url

el alias le GANABA al primary y `byok` salía al cable como nombre de modelo.

MEDIDO sobre la instalada, eligiendo OpenRouter en el panel de La Sala:

    model_route: [{"model":"byok","ok":false,"error":"HTTP 400",
                   "causa":{"detalle":"El proveedor rechazó el pedido (BadRequestError)"}}]
    tool_calls: 0 · model_final: null · usage 0/0/0 · answer ""

Se arregló del lado del ESCRITOR y no del ejecutor: la precedencia es de Gate 2 y está
sellada; hacerla condicional le agrega un caso especial a una regla de una línea.

QUÉ MIDE — dos testigos, y el segundo es el que no se puede falsear:

  1 · LA RECETA · `compileModel("byok", …)` con un payload BYOK NO emite `alias`, y sí emite
      el `primary`, el `base_url` y el `byok_ref` del usuario. Se corre la función REAL del
      módulo, no una copia.
  2 · EL TURNO · un run con herramientas por esa receta → `ok:true`, `tool_calls > 0`,
      `model_final` = el modelo REAL (no "byok"). Una receta linda que no corre no sirve.

NEGATIVO CALIBRADO: se reinyecta `alias:"byok"` en la MISMA receta y el turno tiene que
ROJEAR con `model:"byok"` y `tool_calls:0`.

El turno necesita una llave de OpenRouter en el vault del fixture. Si no hay, el testigo 2 se
declara **NO MEDIBLE** — jamás verde por omisión.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "product" / "backend"))
sys.path.insert(0, str(RAIZ / "platform"))

R: dict[str, dict] = {}


def ok(nombre: str, cond, detalle: str = "") -> None:
    R[nombre] = {"ok": cond, "detalle": detalle}
    marca = "✅" if cond is True else ("⏳" if cond is None else "❌")
    print(f"  {marca} {nombre}" + (f"  · {detalle}" if detalle else ""))


def cerrar() -> int:
    """[H3+H4] EL RESUMEN, POR DONDE SEA QUE SE SALGA.

    Los dos caminos de «no hay binario» / «no hay llave» hacían `return 0` **antes** del
    resumen: la última línea quedaba en un `⏳ 3_negativo_calibrado · sin llave`
    —medido en la regresión de esta fase— y la vara salía CERO sin haber medido nada.
    Las dos cosas juntas: `tail -1` que no es veredicto, y verde sin medición.
    Ahora todo camino pasa por acá, y el veredicto DICE cuántas quedaron sin medir.
    """
    verdes = sum(1 for v in R.values() if v["ok"] is True)
    rojas = sum(1 for v in R.values() if v["ok"] is False)
    grises = sum(1 for v in R.values() if v["ok"] is None)
    print("\n" + "═" * 90)
    print(f"  {verdes} verdes · {rojas} rojas · {grises} no medibles"
          + ("  —  NO CERTIFICA: falta el requisito que dicen los ⏳" if grises and not rojas
             else ""))
    return 1 if rojas else 0


# ── 1 · LA RECETA · se corre `compileModel` DE VERDAD, con node ──────────────────────────
_JS = r"""
const { compileModel } = await import(process.argv[2]);
const r = compileModel("byok", { byok: { provider: "openrouter",
  model: "nvidia/nemotron-3-nano-30b-a3b:free", baseUrl: "https://openrouter.ai/api/v1" } });
console.log(JSON.stringify(r));
"""


def testigo_receta() -> tuple[bool | None, str, dict]:
    mod = RAIZ / "product" / "app" / "design" / "cuarto" / "cuarto.models.js"
    if not mod.exists():
        return None, f"no existe {mod}", {}
    with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False) as fh:
        fh.write(_JS)
        js = fh.name
    try:
        p = subprocess.run(["node", js, mod.as_uri()], capture_output=True, text=True, timeout=90)
    finally:
        os.unlink(js)
    linea = next((l for l in p.stdout.splitlines() if l.startswith("{")), "")
    if not linea:
        return None, f"compileModel no devolvió nada: {(p.stderr or '')[-200:]}", {}
    r = json.loads(linea)
    bien = (
        r.get("alias") in (None, "")
        and r.get("primary") == "nvidia/nemotron-3-nano-30b-a3b:free"
        and r.get("base_url") == "https://openrouter.ai/api/v1"
        and r.get("byok_ref") == "keys:openrouter"
    )
    return bien, json.dumps(r, ensure_ascii=False)[:220], r


# ── 2 · EL TURNO · el mismo sidecar que usa la app ───────────────────────────────────────
def _fixture(datos: Path, llave: str) -> tuple[str, str]:
    os.environ.update({"ALEPH_ROLE": "client", "ALEPH_DATA_DIR": str(datos),
                       "PUPPET_SQLITE_PATH": str(datos / "aleph.db"), "PUPPET_WORKERS": "0"})
    from app.infra import db_boot
    db_boot.asegurar()
    from app.phase1 import repo
    conn = repo.get_conn()
    try:
        d = repo.register_user(conn, email="vara-byok@local.test", password="vara-2026",
                               display_name="Vara")
        repo.upsert_key(conn, user_id=d["id"], provider="openrouter", secret=llave)
    finally:
        conn.close()
    return d["id"], repo.mint_session(d["id"])


def testigo_turno(binario: Path, receta_model: dict, llave: str) -> tuple[bool | None, str]:
    import time
    import urllib.error
    import urllib.request

    tmp = Path(tempfile.mkdtemp(prefix="aleph-vara-byok-"))
    datos = tmp / "datos"
    datos.mkdir(parents=True)
    proc = None
    try:
        owner, tok = _fixture(datos, llave)
        import socket
        s = socket.socket(); s.bind(("127.0.0.1", 0)); puerto = s.getsockname()[1]; s.close()
        base = f"http://127.0.0.1:{puerto}"
        env = dict(os.environ, ALEPH_ROLE="client", ALEPH_DATA_DIR=str(datos),
                   PUPPET_SQLITE_PATH=str(datos / "aleph.db"), TMPDIR=str(tmp))
        proc = subprocess.Popen([str(binario), "--port", str(puerto)], env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True)
        hasta = time.time() + 120
        vivo = False
        while time.time() < hasta:
            try:
                urllib.request.urlopen(base + "/health", timeout=3).read()
                vivo = True
                break
            except Exception:  # noqa: BLE001
                if proc.poll() is not None:
                    break
                time.sleep(0.5)
        if not vivo:
            return None, "el sidecar no arrancó"
        receta = {
            "schema_version": "v1",
            "meta": {"name": "vara-byok", "nicho": "general", "output_type": "informe"},
            "model": receta_model,
            "belt": {"belt_ref": "platform/assembler/fixtures/belt-inline-rich.mcp.json",
                     "tool_filters": {"calc": ["add"]}},
            "framing": {"inline": ""}, "rag": {"enabled": False}, "keys": {},
            "gates": {"money_touch": "needs_ok", "send": "needs_ok"},
        }
        req = urllib.request.Request(
            base + "/v1/puppets/run",
            data=json.dumps({"recipe": receta, "user_id": owner, "lang": "es",
                             "prompt": "Sumá 2 + 2 con la herramienta add. No inventes."}).encode(),
            method="POST",
            headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                out = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            out = json.loads(e.read().decode() or "{}")
        rec = out.get("record") or {}
        ruta = rec.get("model_route") or []
        modelos = [e.get("model") for e in ruta]
        n_tools = len(rec.get("tool_calls") or [])
        det = (f"ok={out.get('ok')} model_final={rec.get('model_final')} "
               f"tool_calls={n_tools} ruta={json.dumps(modelos, ensure_ascii=False)[:90]}")
        bien = bool(out.get("ok")) and n_tools > 0 and rec.get("model_final") not in (None, "", "byok")
        return bien, det
    finally:
        if proc is not None:
            try:
                os.killpg(os.getpgid(proc.pid), 9)
            except Exception:  # noqa: BLE001
                pass
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--sidecar", default="/Applications/Aleph.app/Contents/MacOS/aleph_sidecar")
    ap.add_argument("--llave", default=os.environ.get("ALEPH_VARA_OPENROUTER_KEY", ""),
                    help="llave de OpenRouter para el turno REAL (sin ella: NO MEDIBLE)")
    a = ap.parse_args()

    print("═" * 90)
    print("VARA · ELEGIR TU API EN EL PANEL DEJA UN AGENTE QUE CORRE")
    print("═" * 90)

    print("\n1 · LA RECETA · `compileModel` no emite el alias de la lane")
    bien, det, receta = testigo_receta()
    ok("1_compileModel_no_emite_alias_byok", bien, det)

    print("\n2 · EL TURNO · esa receta corre y llama tools")
    binario = Path(a.sidecar)
    if not binario.exists():
        ok("2_el_turno_corre_y_llama_tools", None, f"no existe {binario}")
        ok("3_negativo_calibrado", None, "sin binario")
        return cerrar()
    if not a.llave:
        ok("2_el_turno_corre_y_llama_tools", None,
           "sin llave de OpenRouter (--llave o ALEPH_VARA_OPENROUTER_KEY) — NO se certifica por omisión")
        ok("3_negativo_calibrado", None, "sin llave")
        return cerrar()
    if not receta:
        ok("2_el_turno_corre_y_llama_tools", False, "no hubo receta que correr")
        return cerrar()
    bien2, det2 = testigo_turno(binario, receta, a.llave)
    ok("2_el_turno_corre_y_llama_tools", bien2, det2)

    print("\n3 · NEGATIVO · con el alias reinyectado, el mismo turno ROJEA")
    con_alias = dict(receta, alias="byok")
    bien3, det3 = testigo_turno(binario, con_alias, a.llave)
    cayo = bien3 is False and ("byok" in det3)
    ok("3_negativo_calibrado", cayo, det3)

    return cerrar()


if __name__ == "__main__":
    raise SystemExit(main())
