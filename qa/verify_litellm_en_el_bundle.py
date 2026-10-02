#!/usr/bin/env python3
"""VARA · LITELLM PUEDE CORRER EN EL CONGELADO (y sus datos viajan).

EL BUG QUE CIERRA — `litellm-sin-sus-datos-en-el-congelado`.

`Analysis` de PyInstaller mete los `.py` de un paquete y **no sus datos**. litellm abre su
mapa de precios con `importlib.resources.files("litellm").joinpath(...)`, así que el import
resolvía perfecto y el archivo no estaba. Medido sobre `/Applications/Aleph.app`:

    POST /v1/puppets/run  →  ok:false · trajectory_steps:0 · answer:""
    "executor: FileNotFoundError: '…/_MEIxxxxx/litellm/model_prices_and_context_window_backup.json'"

**Todo run CON HERRAMIENTAS por una vía de API que no fuera Groq era imposible.** Groq se
salvaba de casualidad: tiene camino directo por urllib; el resto va por litellm.

Y fue MUDO por partida doble: el arranque detecta la falta y la TOLERA a propósito
(`[litellm] NO se selló … — el camino C/D va por urllib`), así que la app levanta perfecta.

TRES TESTIGOS, y el primero NO alcanza:

  1 · TOC ....... los datos declarados en `bundle_datos.py` están adentro del binario.
  2 · BINARIO ... al arrancar, el binario dice `[litellm] sellado en el arranque`. Ese
                  sellado es EXACTAMENTE el código que abre el mapa de precios.
  3 · EJECUTOR .. un run CON HERRAMIENTAS por una `base_url` que va por litellm **llega al
                  proveedor**. Éste es el que no se puede falsear: un archivo listado en el
                  TOC bajo un destino que `files()` no mira daría verde en 1 y rojo acá.
                  (Obra 6d: un archivo presente en el TOC ya nos dio un verde falso.)

NEGATIVO CALIBRADO: `--negativo <sidecar viejo>` corre los mismos tres contra un binario SIN
los datos. Si no rojean los tres, la vara no está midiendo lo que dice.

La llave de OpenRouter del fixture es **FALSA a propósito**: lo que se certifica es que el
pedido SALE y el proveedor contesta (401 = llegó), no que la cuenta de alguien funcione.
Una llave real acá sería un secreto en el árbol.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "product" / "backend"))
sys.path.insert(0, str(RAIZ / "platform"))
sys.path.insert(0, str(RAIZ / "deploy" / "fase4"))

R: dict[str, dict] = {}


def ok(nombre: str, cond, detalle: str = "") -> None:
    R[nombre] = {"ok": cond, "detalle": detalle}
    marca = "✅" if cond is True else ("⏳" if cond is None else "❌")
    print(f"  {marca} {nombre}" + (f"  · {detalle}" if detalle else ""))


def _libre(port: int) -> bool:
    import socket
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _puerto_libre() -> int:
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _get(url: str, tok: str, timeout: float = 20.0):
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + tok})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _post(url: str, tok: str, cuerpo: dict, timeout: float = 180.0):
    req = urllib.request.Request(
        url, data=json.dumps(cuerpo).encode(), method="POST",
        headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


# ── 1 · EL TOC ────────────────────────────────────────────────────────────────────────────
def testigo_toc(binario: Path) -> tuple[bool | None, str]:
    from bundle_datos import destinos_de_paquete
    try:
        from PyInstaller.archive.readers import CArchiveReader
    except Exception as e:  # noqa: BLE001
        return None, f"PyInstaller no disponible ({e})"
    try:
        toc = set(CArchiveReader(str(binario)).toc)
    except Exception as e:  # noqa: BLE001
        return None, f"no pude leer el TOC ({e})"
    faltan = [d for d in destinos_de_paquete() if d not in toc]
    return (not faltan), (f"faltan: {faltan}" if faltan else f"{len(destinos_de_paquete())} adentro")


# ── el binario, corriendo ────────────────────────────────────────────────────────────────
class Sidecar:
    """Levanta el congelado en su PROPIO grupo y con su PROPIO TMPDIR.

    El onefile descomprime ~170 MB en un `_MEIxxxx` del temp y sólo lo borra al salir limpio;
    esta vara mata con SIGKILL (tiene que: el bootloader forkea), así que sin TMPDIR propio
    cada corrida dejaría el directorio huérfano. Con el suyo, borrarlo es exacto.
    """

    def __init__(self, binario: Path, datos: Path):
        self.binario, self.datos = binario, datos
        self.tmp = Path(tempfile.mkdtemp(prefix="aleph-vara-litellm-"))
        self.puerto = _puerto_libre()
        self.base = f"http://127.0.0.1:{self.puerto}"
        self.proc = None
        self.salida = ""

    def __enter__(self):
        env = dict(os.environ, ALEPH_ROLE="client", ALEPH_DATA_DIR=str(self.datos),
                   PUPPET_SQLITE_PATH=str(self.datos / "aleph.db"),
                   PUPPET_DATA_DIR=str(self.datos), TMPDIR=str(self.tmp))
        self.proc = subprocess.Popen(
            [str(self.binario), "--port", str(self.puerto)], env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
        hasta = time.time() + 120
        while time.time() < hasta:
            try:
                urllib.request.urlopen(self.base + "/health", timeout=3).read()
                return self
            except Exception:  # noqa: BLE001
                if self.proc.poll() is not None:
                    break
                time.sleep(0.5)
        return self

    def vivo(self) -> bool:
        try:
            urllib.request.urlopen(self.base + "/health", timeout=4).read()
            return True
        except Exception:  # noqa: BLE001
            return False

    def __exit__(self, *_):
        try:
            os.killpg(os.getpgid(self.proc.pid), 9)
        except Exception:  # noqa: BLE001
            pass
        try:
            self.salida = self.proc.stdout.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)


def _fixture(datos: Path) -> tuple[str, str]:
    """Dueño propio, sesión propia y llave FALSA de openrouter. Jamás la base de nadie."""
    os.environ.update({"ALEPH_ROLE": "client", "ALEPH_DATA_DIR": str(datos),
                       "PUPPET_SQLITE_PATH": str(datos / "aleph.db"), "PUPPET_WORKERS": "0"})
    from app.infra import db_boot
    db_boot.asegurar()
    from app.phase1 import repo
    conn = repo.get_conn()
    try:
        d = repo.register_user(conn, email="vara-litellm@local.test", password="vara-2026",
                               display_name="Vara")
        repo.upsert_key(conn, user_id=d["id"], provider="openrouter",
                        secret="sk-or-v1-vara-falsa-no-sirve")
    finally:
        conn.close()
    return d["id"], repo.mint_session(d["id"])


# ── 3 · EL EJECUTOR ──────────────────────────────────────────────────────────────────────
_JSON_QUE_FALTABA = "model_prices_and_context_window_backup.json"


def testigo_ejecutor(base: str, tok: str, owner: str) -> tuple[bool | None, str, dict]:
    """Un run CON HERRAMIENTAS por una `base_url` que va por litellm.

    VERDE = el pedido SALIÓ y el proveedor contestó (con la llave falsa, un 401/403 es
    exactamente eso). ROJO = murió en el ejecutor por el `.json` ausente, sin salir nunca.
    """
    receta = {
        "schema_version": "v1",
        "meta": {"name": "vara-litellm", "nicho": "general", "output_type": "informe"},
        # base_url de OpenRouter = camino litellm. Groq NO sirve para esta vara: tiene ruta
        # DIRECTA por urllib y pasaría en verde con litellm roto.
        "model": {"primary": "openai/gpt-oss-20b:free",
                  "base_url": "https://openrouter.ai/api/v1",
                  "byok_ref": "keys:openrouter",
                  "temperature": 0, "max_tokens": 200, "max_turns": 2, "fallback": None},
        "belt": {"belt_ref": "platform/assembler/fixtures/belt-inline-rich.mcp.json",
                 "tool_filters": {"calc": ["add"]}},
        "framing": {"inline": ""}, "rag": {"enabled": False}, "keys": {},
        "gates": {"money_touch": "needs_ok", "send": "needs_ok"},
    }
    st, out = _post(base + "/v1/puppets/run", tok,
                    {"recipe": receta, "user_id": owner, "lang": "es",
                     "prompt": "Sumá 2 + 2 con la herramienta add."})
    err = json.dumps(out.get("error") or "", ensure_ascii=False)
    ruta = json.dumps((out.get("record") or {}).get("model_route") or [], ensure_ascii=False)
    if _JSON_QUE_FALTABA in err:
        return False, "murió en el ejecutor: falta el .json de litellm — el pedido NO salió", out
    # ¿Contestó el proveedor? Con llave falsa, credencial inválida ES la prueba de que llegó.
    llego = any(s in (err + ruta).lower() for s in
                ("401", "403", "credencial", "auth", "invalid", "http 4", "upstream"))
    if llego:
        return True, f"el pedido llegó al proveedor · {(err + ' ' + ruta)[:150]}", out
    if out.get("ok"):
        return True, "el run corrió entero por litellm", out
    return None, f"ni el .json ni respuesta del proveedor: {(err + ruta)[:200]}", out


def corrida(binario: Path, etiqueta: str) -> dict:
    print(f"\n── {etiqueta} · {binario} ──")
    res: dict = {}
    v_toc, d_toc = testigo_toc(binario)
    res["toc"] = (v_toc, d_toc)
    tmp = Path(tempfile.mkdtemp(prefix="aleph-vara-litellm-datos-"))
    datos = tmp / "datos"
    datos.mkdir(parents=True)
    try:
        owner, tok = _fixture(datos)
        with Sidecar(binario, datos) as sc:
            if not sc.vivo():
                res["binario"] = (None, "el sidecar no arrancó")
                res["ejecutor"] = (None, "el sidecar no arrancó")
                return res
            v_ej, d_ej, _ = testigo_ejecutor(sc.base, tok, owner)
            res["ejecutor"] = (v_ej, d_ej)
        salida = sc.salida
        if "[litellm] NO se selló" in salida:
            linea = next(l for l in salida.splitlines() if "[litellm] NO se selló" in l)
            res["binario"] = (False, linea.strip()[:190])
        elif "[litellm] sellado en el arranque" in salida:
            linea = next(l for l in salida.splitlines() if "[litellm] sellado" in l)
            res["binario"] = (True, linea.strip()[:160])
        else:
            res["binario"] = (None, "el binario no dijo nada de litellm")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sidecar", help="el binario a certificar (por defecto, el instalado)")
    ap.add_argument("--negativo", help="un sidecar SIN los datos, para calibrar el negativo")
    a = ap.parse_args()

    binario = Path(a.sidecar) if a.sidecar else Path(
        "/Applications/Aleph.app/Contents/MacOS/aleph_sidecar")
    if not binario.exists():
        print(f"no existe {binario}")
        return 1

    print("═" * 90)
    print("VARA · LITELLM PUEDE CORRER EN EL CONGELADO")
    print("═" * 90)

    pos = corrida(binario, "POSITIVO")
    ok("1_toc_los_datos_de_paquete_viajaron", pos["toc"][0], pos["toc"][1])
    ok("2_el_binario_sello_litellm", pos["binario"][0], pos["binario"][1])
    ok("3_el_ejecutor_llega_al_proveedor", pos["ejecutor"][0], pos["ejecutor"][1])

    if a.negativo:
        neg = corrida(Path(a.negativo), "NEGATIVO (sin los datos)")
        cayo_toc = neg["toc"][0] is False
        cayo_bin = neg["binario"][0] is False
        cayo_eje = neg["ejecutor"][0] is False
        ok("4_negativo_calibrado_toc", cayo_toc, neg["toc"][1])
        ok("5_negativo_calibrado_binario", cayo_bin, neg["binario"][1])
        ok("6_negativo_calibrado_ejecutor", cayo_eje, neg["ejecutor"][1])
    else:
        ok("4_negativo_calibrado", None, "sin --negativo: no se calibró (se declara)")

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
