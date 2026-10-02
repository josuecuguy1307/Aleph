#!/usr/bin/env python3
"""VARA · LA SALA RESTAURA UN BYOK CON SU PAYLOAD (no sólo cuando le hacés click).

EL BUG QUE CIERRA — `la-restauración-no-pasa-por-el-puente`.

`applySalaSelectedModel()` es el camino de RESTAURAR la elección persistida al cargar la
Sala. Escribía el `picker_id` CRUDO en `ST.power` y ponía `ST.byok = null`:

    elegido = vivo.id;              // 'api:openrouter'
    ST.power = elegido;             // nunca 'tuapi'
    ST.byok  = null;                // ← el payload que el sidecar YA entregó, al tacho

Para toda fila de API el turno salía con la receta vacía y el backend lo rechazaba:

    receta {primary:"", base_url:"", alias:"byok"}
      → POST /v1/puppets/run/stream → 422 recipe_invalid
         «model.primary requerido» · «model.base_url requerido»

Desde afuera se ve exactamente así: **el proveedor figura conectado, la verificación dice
que la llave sirve, y La Sala no responde**. Medido sobre la app instalada con la cuenta
real antes de tocar nada.

Es la MISMA trampa que `powPick` documenta al pie («el id de poder de un BYOK en la Sala es
`tuapi`, NO `byok`; confundirlos compila la receta SIN el payload»). La obra D puso el
puente `curadoDesdeFila` en el camino del CLICK y dejó éste, el de restaurar, sin él.

QUÉ MIDE, y por qué en un navegador de verdad: el testigo es la receta EFECTIVA que la Sala
va a mandar —`window.__salaCerebro.aCorrer()`, el hook que dejó la obra B—, no un espejo de
la lógica rearmado acá. Rearmarlo mediría mi copia, no el producto.

  1 · POSITIVO      · fila de API restaurada → `power='tuapi'` y la receta lleva el `primary`
                      y el `base_url` que entregó el sidecar (los MISMOS, comparados).
  2 · NEGATIVO      · con el código VIEJO servido en el lugar del nuevo, el mismo testigo
                      tiene que ROJEAR. Sin esto la vara podría estar pasando por otra razón.
  3 · DISCRIMINANTE · una fila `cli.*` restaurada NO se vuelve `tuapi`: el arreglo traduce
                      las de API, no convierte todo en BYOK.

El fixture es PROPIO (usuario, sesión y llave FALSA nuevos, en un dir temporal). Jamás la
base del dueño: esta vara crea una cuenta, y crearla en la base de alguien es medir sobre su
estado.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "product" / "backend"))
sys.path.insert(0, str(RAIZ / "platform"))

R: dict[str, dict] = {}


def ok(nombre: str, cond: bool, detalle: str = "") -> None:
    R[nombre] = {"ok": bool(cond), "detalle": detalle}
    print(f"  {'✅' if cond else '❌'} {nombre}" + (f"  · {detalle}" if detalle else ""))


def no_medible(nombre: str, motivo: str) -> None:
    R[nombre] = {"ok": None, "detalle": motivo}
    print(f"  ⏳ NO MEDIBLE {nombre} · {motivo}")


# El separador de las claves del motor es \x1f (unit separator), no un guion: la clave es
# `key␟<provider>␟<owner>`. Escribirla con otro separador deja el veredicto invisible y la
# fila sale `detectado` — o sea, la vara no mediría nada.
SEP = "\x1f"


def _escribir_fixture(datos: Path, owner: str) -> None:
    """Un dueño con OpenRouter PROBADO y elegido para la Sala.

    `conectado` de una fila de API exige VEREDICTO, no «hay una llave en el vault» (regla de
    F7·A). Sin el veredicto la fila no entra al pool, `applySalaSelectedModel` no encuentra
    a quién restaurar, y esta vara pasaría en verde sin haber medido el camino.
    """
    (datos / "modelos").mkdir(parents=True, exist_ok=True)
    (datos / "modelos" / "preferencias-v2.json").write_text(json.dumps({
        "version": 2,
        "default": "api.openrouter",
        "conectados": ["api.openrouter"],
        "contextos": {"sala": "api.openrouter"},
        "modelos": {"api.openrouter": "openai/gpt-oss-20b:free"},
        "actualizado_en": time.time(),
    }, ensure_ascii=False), encoding="utf-8")
    (datos / "motor_estado.json").write_text(json.dumps({
        "v": 1,
        "estados": {
            f"key{SEP}openrouter{SEP}{owner}": {
                "tipo": "key", "ref": "openrouter", "estado": "probado", "causa": None,
                "evidencia": {"motivo": "fixture de vara", "provider": "openrouter"},
                "ts": time.time(),
            },
        },
    }, ensure_ascii=False), encoding="utf-8")


def _fixture_cli(datos: Path) -> None:
    """El DISCRIMINANTE: el mismo dir, pero con un CLI elegido para la Sala."""
    (datos / "modelos" / "preferencias-v2.json").write_text(json.dumps({
        "version": 2,
        "default": "cli.claude_cli",
        "conectados": ["cli.claude_cli"],
        "contextos": {"sala": "cli.claude_cli"},
        "modelos": {},
        "actualizado_en": time.time(),
    }, ensure_ascii=False), encoding="utf-8")


def _correr_front(datos: Path, modo: str) -> dict:
    front = RAIZ / "qa" / "verify_sala_restaura_byok_front.mjs"
    if not front.exists():
        return {"_falta": str(front)}
    if not (RAIZ / "node_modules" / "playwright").exists():
        return {"_sin_playwright": True}
    p = subprocess.run(
        ["node", str(front)], cwd=str(RAIZ),
        env=dict(os.environ, ALEPH_DATA_DIR=str(datos), ALEPH_VARA_MODO=modo),
        capture_output=True, text=True, timeout=300,
    )
    linea = next((l for l in reversed(p.stdout.splitlines()) if l.startswith("{")), "")
    if not linea:
        return {"_sin_salida": (p.stderr or p.stdout)[-500:]}
    return json.loads(linea)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="aleph-vara-salabyok-"))
    datos = tmp / "datos"
    datos.mkdir(parents=True)
    os.environ.update({
        "ALEPH_ROLE": "client",
        "ALEPH_DATA_DIR": str(datos),
        "PUPPET_SQLITE_PATH": str(datos / "aleph.db"),
        "PUPPET_WORKERS": "0",
    })
    try:
        from app.infra import db_boot
        db_boot.asegurar()
        from app.phase1 import repo
        conn = repo.get_conn()
        try:
            duena = repo.register_user(conn, email="vara-salabyok@local.test",
                                       password="vara-2026", display_name="Vara")
            # LLAVE FALSA A PROPÓSITO: la vara mide qué RECETA arma el frente, no si el
            # proveedor contesta. Una llave real acá sería un secreto en el árbol.
            repo.upsert_key(conn, user_id=duena["id"], provider="openrouter",
                            secret="sk-or-v1-vara-no-sirve-para-nada")
        finally:
            conn.close()
        owner = duena["id"]
        os.environ["ALEPH_VARA_TOKEN"] = repo.mint_session(owner)
        os.environ["ALEPH_VARA_OWNER"] = owner
        _escribir_fixture(datos, owner)

        print("═" * 90)
        print("VARA · LA SALA RESTAURA UN BYOK CON SU PAYLOAD")
        print(f"  fixture: {datos}")
        print(f"  dueña  : {owner}")
        print("═" * 90)

        print("\n1 · POSITIVO · la fila de API restaurada llega con su payload")
        pos = _correr_front(datos, "positivo")
        if pos.get("_sin_playwright"):
            no_medible("1_positivo", "playwright no está instalado en este árbol")
            no_medible("2_negativo", "playwright no está instalado en este árbol")
            no_medible("3_discriminante", "playwright no está instalado en este árbol")
            return 0
        if pos.get("_falta") or pos.get("_sin_salida"):
            ok("1_positivo", False, json.dumps(pos)[:300])
            return 1
        for k, v in pos.items():
            ok(k, v.get("ok"), json.dumps(v.get("detalle"), ensure_ascii=False)[:220])

        print("\n2 · NEGATIVO · con el código viejo, el mismo testigo ROJEA")
        neg = _correr_front(datos, "negativo")
        cayo = neg.get("1a_power_es_tuapi", {}).get("ok") is False \
            and neg.get("1b_la_receta_lleva_el_modelo", {}).get("ok") is False
        ok("2_negativo_calibrado", cayo,
           "con el bug puesto: power=" + str(neg.get("1a_power_es_tuapi", {}).get("detalle"))
           + " · receta=" + json.dumps(neg.get("1b_la_receta_lleva_el_modelo", {}).get("detalle"),
                                       ensure_ascii=False)[:160])

        print("\n3 · DISCRIMINANTE · un CLI restaurado NO se vuelve BYOK")
        _fixture_cli(datos)
        dis = _correr_front(datos, "discriminante")
        for k, v in dis.items():
            ok(k, v.get("ok"), json.dumps(v.get("detalle"), ensure_ascii=False)[:220])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    verdes = sum(1 for v in R.values() if v["ok"] is True)
    rojas = sum(1 for v in R.values() if v["ok"] is False)
    grises = sum(1 for v in R.values() if v["ok"] is None)
    # [H3] La barra decorativa va ARRIBA. Con ella al final, `tail -1` leía «═════…» en
    # vez del conteo — medido en la regresión de esta fase, en las tres varas del cierre
    # de §28 que comparten este cierre copiado.
    print("\n" + "═" * 90)
    print(f"  {verdes} verdes · {rojas} rojas · {grises} no medibles")
    return 1 if rojas else 0


if __name__ == "__main__":
    raise SystemExit(main())
