#!/usr/bin/env python3
"""verify_costura_obra4.py — Vara única Gate 3 · Obra 4: LA SESIÓN SOBREVIVE AL REINICIO (D9).

Mide el mapa `clave→session_id` en disco: que se escriba con tres campos y nada más, que
una instancia y un PROCESO nuevos lo restauren, que un id que el CLI ya no tiene caiga a
sesión nueva diciendo `sesion_perdida` (causa sellada en F1c) sin romper el turno, que un
archivo roto no tumbe el arranque, y que la escritura sea atómica de verdad.

TRES AISLAMIENTOS, y los tres antes del primer import de `cli_brain`:

  · `PUPPET_CLI_SESIONES_DIR`  → el workdir de la vara CALCA el de producción (espacio Y
    guión bajo: la lección de F4d, donde un `mkdtemp` limpio escondió el bug una fase
    entera). El mapa vive adentro, así que esta perilla también lo aísla.
  · `CLAUDE_CONFIG_DIR`        → el store del CLI es FALSO. Esta vara no lee ni escribe
    una sola conversación del usuario: el store real ni se toca.
  · `PUPPET_CLI_PROCESOS`      → el registro de F2d, fuera del datadir real.

Y el turno corre contra un PROVEEDOR FALSO: cero spawns, cero red, resultado determinista.
Lo que se mide acá es la costura del mapa, no el binario — el binario lo mide V6, que
corre la vara de F2e entera contra el CLI real.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BACKEND = ROOT / "product" / "backend"
for _p in (str(HERE), str(ROOT / "platform"), str(BACKEND)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── EL AISLAMIENTO, ANTES DE IMPORTAR NADA DE cli_brain ────────────────────────────
TMP = Path(tempfile.mkdtemp(prefix="vara-obra4-"))
RAIZ_SESIONES = TMP / "Application Support" / "Aleph" / "cli_sesiones"
STORE_FALSO = TMP / "claude-falso"
os.environ["PUPPET_CLI_SESIONES_DIR"] = str(RAIZ_SESIONES)
os.environ["PUPPET_CLI_PROCESOS"] = str(TMP / "cli_procesos.jsonl")
os.environ["CLAUDE_CONFIG_DIR"] = str(STORE_FALSO)
os.environ["PUPPET_CLI_SESIONES"] = "1"

from cli_brain import base as B                        # noqa: E402
from cli_brain import detect as _detect                # noqa: E402
from cli_brain import sesiones as S                    # noqa: E402
from cli_brain import slots as SL                      # noqa: E402
from cli_brain.server import create_server             # noqa: E402

#: Marcador que viaja DENTRO de la conversación. Si aparece en el mapa, el límite de
#: contenido (O4) está roto. Es la misma técnica que la vara de la obra 3.
SECRETO = "SECRETO-DE-LA-CHARLA-9f3a7c1e"

PASSED = 0
FAILED = 0


def check(name: str, condition: bool, detail: Any = "") -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"PASS {name}" + (f" — {detail}" if detail else ""))
    else:
        FAILED += 1
        print(f"FAIL {name}" + (f" — {detail}" if detail else ""))


def seccion(t: str) -> None:
    print(f"\n── {t} " + "─" * max(0, 74 - len(t)))


# ══ EL PROVEEDOR FALSO ══════════════════════════════════════════════════════════════
class ProveedorFalso:
    """Un CLI que no existe. Contesta siempre bien, salvo los ids que se le declaren
    perdidos — que es como se simula «el CLI ya no reconoce esa conversación» sin
    depender de que haya un binario instalado ni de qué versión sea."""

    provider_id = "claude_cli"
    display_name = "CLI de la vara"
    response_model_id = "claude-code-cli"

    def __init__(self):
        self.turnos: list = []
        self.perdidos: set = set()

    def invoke(self, prompt, model=None, effort=None, timeout=None, sesion=None,
               turno_id=None, on_evento=None):
        modo = "nueva" if (sesion is None or sesion.fresca) else "resume"
        self.turnos.append({"modo": modo, "prompt": prompt,
                            "sesion_id": None if sesion is None else sesion.id})
        if sesion is not None and modo == "resume" and sesion.id in self.perdidos:
            return B.BrainResult(
                ok=False, error_kind=B.ERR_SESION_PERDIDA,
                error_detail=f"No conversation found with session ID: {sesion.id}",
                meta={"sesion_perdida": True}, causa=S.causa_de_resume(sesion.id))
        return B.BrainResult(ok=True, text="LISTO", model_final="stub-de-la-vara",
                             model_final_source="cli-reported",
                             usage={"prompt_tokens": None, "completion_tokens": None},
                             tokens_medidos=False)


FALSO = ProveedorFalso()


# ══ UTILIDADES ══════════════════════════════════════════════════════════════════════
def plantar_transcript(sesion_id: str, workdir: str) -> Path:
    """Lo que el CLI deja en su store cuando una sesión existe de verdad: un `.jsonl`
    con el sessionId de nombre, bajo el slug del cwd. Acá el store es el falso."""
    d = Path(S.raiz_del_store()) / S.slug_de(workdir)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{sesion_id}.jsonl"
    p.write_text(json.dumps({"type": "system", "sessionId": sesion_id, "cwd": workdir,
                             "timestamp": "2026-08-06T12:00:00.000Z"}) + "\n",
                 encoding="utf-8")
    return p


def filas_del_mapa() -> list:
    """Las filas CRUDAS del archivo, parseadas acá y no por el módulo: la vara tiene que
    poder decir qué hay en el disco aunque el lector del módulo estuviera mal."""
    try:
        crudo = Path(S.SESIONES.mapa_ruta).read_text(encoding="utf-8")
    except OSError:
        return []
    return [json.loads(l) for l in crudo.splitlines() if l.strip()]


def sha_del_mapa() -> str:
    try:
        return hashlib.sha256(Path(S.SESIONES.mapa_ruta).read_bytes()).hexdigest()
    except OSError:
        return ""


def reiniciar_proceso() -> None:
    """EL REINICIO SIMULADO: se tira el registro entero y se construye uno nuevo, que es
    exactamente lo que hace un proceso al arrancar. El módulo no se recarga a propósito —
    el estado que esta obra persiste vive en la instancia, no en el módulo."""
    S.SESIONES = S.Sesiones()


def post(puerto: int, cuerpo: dict, *, ruta: str = "/v1/chat/completions") -> tuple:
    import http.client
    conn = http.client.HTTPConnection("127.0.0.1", puerto, timeout=60)
    conn.request("POST", ruta, json.dumps(cuerpo),
                 {"Content-Type": "application/json", "Host": f"127.0.0.1:{puerto}"})
    r = conn.getresponse()
    bruto = r.read().decode("utf-8", "replace")
    conn.close()
    try:
        return r.status, json.loads(bruto)
    except (json.JSONDecodeError, ValueError):
        return r.status, {"_crudo": bruto[:400]}


def mensajes(n: int) -> list:
    """Una conversación con el marcador adentro, para poder probar que NO llega al mapa."""
    msgs = [{"role": "system", "content": f"Sos un agente de prueba. {SECRETO}"}]
    for i in range(n):
        msgs.append({"role": "user", "content": f"turno {i} · {SECRETO}"})
        if i < n - 1:
            msgs.append({"role": "assistant", "content": f"ok {i}"})
    return msgs


def env_limpio() -> dict:
    """El entorno para las varas HIJAS: sin NINGUNA de nuestras perillas.

    `CLAUDE_CONFIG_DIR` es la que obliga: mueve el store del CLI **y se lleva puesto el
    auth** (medido en F2e, punto 7). Heredarlo dejaría a la vara de F2e sin poder hablar
    con el CLI real y su parte viva se saltearía sola — verde por no haber medido.
    """
    env = dict(os.environ)
    for k in ("PUPPET_CLI_SESIONES_DIR", "PUPPET_CLI_PROCESOS", "CLAUDE_CONFIG_DIR",
              "PUPPET_CLI_SESIONES_MAPA"):
        env.pop(k, None)
    return env


# ══════════════════════════════════════════════════════════════════════════════════════
def main() -> int:
    print("=== verify_costura_obra4 · D9 · la sesión sobrevive al reinicio ===")
    print(f"    raiz de sesiones : {RAIZ_SESIONES}")
    print(f"    store FALSO      : {STORE_FALSO}")

    guardado = dict(_detect._BY_MODEL_ID)
    _detect._BY_MODEL_ID["claude-code-cli"] = FALSO
    srv = create_server(0)
    puerto = srv.server_port
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    try:
        # ══ V1 · EL ALTA ═══════════════════════════════════════════════════════════
        seccion("V1 · alta de sesión → el mapa en disco: clave · sesion_id · ts, y NADA más")
        SL.SLOTS.reiniciar()
        S.SESIONES.reiniciar()
        CLAVE = "vara-obra4-" + uuid.uuid4().hex[:8]

        # El turno 1 abre sesión. El «CLI» escribe su transcript: sin eso no hay nada que
        # resumir, y el mapa —a propósito— no guarda promesas.
        ses = S.SESIONES.obtener(CLAVE, "claude_cli")
        plantar_transcript(ses.id, ses.workdir)
        st1, r1 = post(puerto, {"model": "claude-code-cli", "sesion": CLAVE,
                                "messages": mensajes(1)})
        ax1 = (r1.get("aleph_cli_brain") or {}).get("sesion") or {}
        id_vivo = ax1.get("id")
        check("V1 el turno de alta sale bien", st1 == 200 and bool(id_vivo),
              f"status={st1} annex={ax1}")

        filas = filas_del_mapa()
        check("V1 el mapa EXISTE en disco con UNA fila",
              len(filas) == 1, f"{S.SESIONES.mapa_ruta} → {filas}")
        fila = filas[0] if filas else {}
        check("V1 la fila tiene clave, sesion_id y timestamp",
              fila.get("clave") == CLAVE and fila.get("sesion_id") == id_vivo
              and isinstance(fila.get("ts"), (int, float)), str(fila))
        check("V1 y NADA más que eso (`v` es el sello de versión, no un dato)",
              set(fila.keys()) == {"v", "clave", "sesion_id", "ts"}
              and fila.get("v") == S.MAPA_V, str(sorted(fila.keys())))

        crudo = Path(S.SESIONES.mapa_ruta).read_text(encoding="utf-8")
        check("V1 CERO contenido de conversación en el archivo",
              SECRETO not in crudo and "turno 0" not in crudo and "LISTO" not in crudo,
              f"{len(crudo)} bytes: {crudo.strip()[:160]}")

        # Y el turno 2 no vuelve a escribir: el id no cambió.
        sha_antes = sha_del_mapa()
        st2, r2 = post(puerto, {"model": "claude-code-cli", "sesion": CLAVE,
                                "messages": mensajes(2)})
        check("V1 un turno que no cambia el id NO reescribe el archivo",
              st2 == 200 and sha_del_mapa() == sha_antes and len(filas_del_mapa()) == 1,
              f"status={st2}")

        # ══ V2 · EL REINICIO ═══════════════════════════════════════════════════════
        seccion("V2 · reinicio → la misma clave resuelve el MISMO session_id")
        reiniciar_proceso()
        check("V2 el registro nuevo arranca SIN sesiones vivas",
              S.SESIONES.estado()["vivas"] == 0, str(S.SESIONES.estado()["vivas"]))
        check("V2 …y con el mapa CARGADO del disco",
              S.SESIONES.cargar() == 1, str(S.SESIONES.estado()["mapa"]))

        rest = S.SESIONES.obtener(CLAVE, "claude_cli")
        check("V2 la misma clave resuelve el MISMO session_id",
              rest is not None and rest.id == id_vivo, f"{rest and rest.id} vs {id_vivo}")
        check("V2 y NO es fresca: el próximo turno RESUME, no abre sesión nueva",
              rest is not None and rest.restaurada is True and rest.fresca is False,
              f"restaurada={rest and rest.restaurada} fresca={rest and rest.fresca}")

        # El proceso nuevo DE VERDAD: otro intérprete, mismo entorno, cero estado heredado.
        hijo = TMP / "hijo_reinicio.py"
        hijo.write_text(
            "import json, sys\n"
            f"sys.path.insert(0, {str(HERE)!r})\n"
            "from cli_brain import sesiones as S\n"
            f"s = S.SESIONES.obtener({CLAVE!r}, 'claude_cli')\n"
            "print(json.dumps({'id': s.id, 'restaurada': s.restaurada, 'fresca': s.fresca,\n"
            "                  'entradas': S.SESIONES.estado()['mapa']['entradas']}))\n",
            encoding="utf-8")
        salida = subprocess.run([sys.executable, str(hijo)], capture_output=True, text=True,
                                cwd=str(ROOT), env=dict(os.environ))
        try:
            visto = json.loads((salida.stdout or "").strip().splitlines()[-1])
        except (ValueError, IndexError):
            visto = {"_stdout": salida.stdout, "_stderr": salida.stderr[-300:]}
        check("V2 un PROCESO nuevo restaura el mismo id (no sólo una instancia nueva)",
              visto.get("id") == id_vivo and visto.get("restaurada") is True
              and visto.get("fresca") is False and visto.get("entradas") == 1, str(visto))

        # ── el reloj NO vence el mapa, y podar tampoco lo borra ────────────────────
        # Las dos son la misma decisión mirada de los dos lados: quien sabe si una
        # conversación existe todavía es el store del CLI, no nuestro TTL. Si el TTL
        # venciera el mapa, cerrar la app de noche y abrirla a la mañana no restauraría
        # NADA — o sea, la obra entera sería decoración.
        vieja_clave = "vara-obra4-vieja"
        v = S.SESIONES.obtener(vieja_clave, "claude_cli")
        plantar_transcript(v.id, v.workdir)
        S.SESIONES.recordar(v)
        # Se envejecen TODAS las filas diez días, sin depender de en qué renglón quedó
        # cada una: el archivo se escribe por `ts` DESCENDENTE, y atar la vara a ese
        # orden la haría medir la fila de al lado sin que nadie se entere.
        diez_dias = 10 * 24 * 3600
        antes_de_envejecer = {f["clave"]: f["sesion_id"] for f in filas_del_mapa()}
        Path(S.SESIONES.mapa_ruta).write_text(
            "".join(json.dumps({**f, "ts": f["ts"] - diez_dias}) + "\n"
                    for f in filas_del_mapa()), encoding="utf-8")
        reiniciar_proceso()
        n_viejas = S.SESIONES.cargar()
        check("V2 una entrada de hace DIEZ DÍAS sigue restaurando (el TTL de proceso no "
              "vence el mapa: el que decide es el store del CLI)",
              n_viejas == len(antes_de_envejecer)
              and antes_de_envejecer.get(vieja_clave) == v.id
              and S.SESIONES.obtener(vieja_clave, "claude_cli").id == v.id
              and S.SESIONES.obtener(CLAVE, "claude_cli").id == id_vivo,
              f"cargadas={n_viejas} de {len(antes_de_envejecer)} · "
              f"{S.SESIONES.obtener(vieja_clave, 'claude_cli').id} vs {v.id}")

        # y podar por TTL saca la sesión de memoria SIN olvidarla en disco
        S.SESIONES._vivas[vieja_clave].ultimo_uso = 0.0
        S.SESIONES.obtener("vara-obra4-disparador", "claude_cli")   # dispara la poda
        check("V2 podar por TTL libera la memoria y el workdir, pero NO olvida el mapa",
              vieja_clave not in S.SESIONES._vivas
              and vieja_clave in [f.get("clave") for f in filas_del_mapa()],
              f"vivas={list(S.SESIONES._vivas)} mapa={[f.get('clave') for f in filas_del_mapa()]}")
        # …y cerrar SÍ olvida: es una decisión de quien llama, no del reloj
        S.SESIONES.obtener(vieja_clave, "claude_cli")
        S.SESIONES.cerrar(vieja_clave)
        S.SESIONES.cerrar("vara-obra4-disparador")
        check("V2 …pero `cerrar()` sí olvida (esa conversación terminó)",
              vieja_clave not in [f.get("clave") for f in filas_del_mapa()],
              str([f.get("clave") for f in filas_del_mapa()]))

        # …y el turno del reencuentro RESUME de verdad, y manda el historial completo.
        S.SESIONES.obtener(CLAVE, "claude_cli")
        n_antes = len(FALSO.turnos)
        st3, r3 = post(puerto, {"model": "claude-code-cli", "sesion": CLAVE,
                                "messages": mensajes(3)})
        ax3 = (r3.get("aleph_cli_brain") or {}).get("sesion") or {}
        turno_reencuentro = FALSO.turnos[n_antes] if len(FALSO.turnos) > n_antes else {}
        check("V2 el turno del reencuentro va con RESUME sobre el id restaurado",
              st3 == 200 and turno_reencuentro.get("modo") == "resume"
              and turno_reencuentro.get("sesion_id") == id_vivo,
              f"status={st3} turno={turno_reencuentro.get('modo')} annex={ax3}")
        check("V2 y lo dice honesto: restaurada=True, incremental=False (mandó TODO)",
              ax3.get("restaurada") is True and ax3.get("incremental") is False
              and ax3.get("causa") is None, str(ax3))
        check("V2 el historial COMPLETO viajó (los tres turnos, no sólo la cola)",
              all(f"turno {i}" in turno_reencuentro.get("prompt", "") for i in range(3)),
              turno_reencuentro.get("prompt", "")[:120])

        # ══ V3 · EL ID VENCIDO ═════════════════════════════════════════════════════
        seccion("V3 · session_id vencido → sesión nueva, turno completo, `sesion_perdida`")
        # (a) el store ya no tiene ese transcript: es el caso «store rotado / borrado /
        #     proyecto movido» que O2b nombra, y lo caza el `isfile` previo al resume.
        reiniciar_proceso()
        ses_v = S.SESIONES.obtener(CLAVE, "claude_cli")
        id_viejo = ses_v.id
        os.remove(S.ruta_de_sesion(id_viejo, ses_v.workdir))
        check("V3 el transcript ya no está en el store",
              S.existe_sesion(id_viejo, ses_v.workdir) is False, id_viejo)

        st4, r4 = post(puerto, {"model": "claude-code-cli", "sesion": CLAVE,
                                "messages": mensajes(4)})
        ax4 = (r4.get("aleph_cli_brain") or {}).get("sesion") or {}
        check("V3 el turno COMPLETA igual (no se rompe por una sesión vencida)",
              st4 == 200, f"status={st4} {str(r4)[:200]}")
        check("V3 con una sesión NUEVA (el id viejo se abandonó)",
              bool(ax4.get("id")) and ax4.get("id") != id_viejo,
              f"{ax4.get('id')} vs {id_viejo}")
        causa = ax4.get("causa") or {}
        check("V3 y la causa SELLADA `sesion_perdida` viaja en el evento del turno",
              causa.get("causa") == "sesion_perdida"
              and causa.get("evidencia", {}).get("guard") == "sesion_perdida"
              and causa.get("reintentable") is True, str(causa)[:220])
        check("V3 CERO causa nueva: es la de F1c, la misma que emite `causa_de_resume`",
              causa.get("causa") == (S.causa_de_resume("x") or {}).get("causa"),
              str((S.causa_de_resume('x') or {}).get('causa')))
        ids_mapa = [f.get("sesion_id") for f in filas_del_mapa()]
        check("V3 la entrada vencida se LIMPIÓ del mapa (ese id no vuelve nunca)",
              id_viejo not in ids_mapa, f"mapa={ids_mapa}")

        # y se registra UNA vez: el turno siguiente ya no repite la causa
        st5, r5 = post(puerto, {"model": "claude-code-cli", "sesion": CLAVE,
                                "messages": mensajes(5)})
        ax5 = (r5.get("aleph_cli_brain") or {}).get("sesion") or {}
        check("V3 se registra UNA sola vez (el turno siguiente ya no la repite)",
              st5 == 200 and ax5.get("causa") is None and ax5.get("restaurada") is False,
              str(ax5))

        # (b) el CLI la rechaza a mitad de vuelo, con el transcript presente: el server
        #     rehace el turno con contexto completo en vez de fallarlo.
        SL.SLOTS.reiniciar()
        S.SESIONES.reiniciar()
        CLAVE_B = "vara-obra4-b-" + uuid.uuid4().hex[:8]
        ses_b = S.SESIONES.obtener(CLAVE_B, "claude_cli")
        plantar_transcript(ses_b.id, ses_b.workdir)
        post(puerto, {"model": "claude-code-cli", "sesion": CLAVE_B, "messages": mensajes(1)})
        reiniciar_proceso()
        ses_b2 = S.SESIONES.obtener(CLAVE_B, "claude_cli")
        FALSO.perdidos.add(ses_b2.id)              # el CLI simulado NO lo reconoce
        id_b = ses_b2.id
        st6, r6 = post(puerto, {"model": "claude-code-cli", "sesion": CLAVE_B,
                                "messages": mensajes(2)})
        ax6 = (r6.get("aleph_cli_brain") or {}).get("sesion") or {}
        check("V3 (bis) si el CLI rechaza el resume a mitad, el turno igual COMPLETA",
              st6 == 200 and ax6.get("rehecha") is True and ax6.get("id") != id_b,
              f"status={st6} {ax6}")
        check("V3 (bis) …con la causa `sesion_perdida` (venía del mapa) en el mismo turno",
              (ax6.get("causa") or {}).get("causa") == "sesion_perdida",
              str(ax6.get("causa"))[:180])
        check("V3 (bis) …y el id muerto NO sobrevive en el mapa: no se reintenta al "
              "próximo arranque",
              id_b not in [f.get("sesion_id") for f in filas_del_mapa()],
              f"mapa={[f.get('sesion_id') for f in filas_del_mapa()]}")

        # ══ V4 · EL ARCHIVO ROTO ═══════════════════════════════════════════════════
        seccion("V4 · archivo corrupto → boot limpio, mapa vacío, declarado, cero excepción")
        Path(S.SESIONES.mapa_ruta).write_bytes(b"\x00\xff\xfe basura que no es json\n{{{\n")
        try:
            reiniciar_proceso()
            n = S.SESIONES.cargar()
            reventó = ""
        except Exception as e:                      # noqa: BLE001
            n, reventó = -1, f"{type(e).__name__}: {e}"
        check("V4 bytes basura → mapa VACÍO y CERO excepción",
              n == 0 and not reventó, f"entradas={n} excepción={reventó!r}")
        check("V4 …y una clave cualquiera arranca de cero, sin restaurar nada",
              S.SESIONES.obtener("clave-tras-basura", "claude_cli").restaurada is False)

        # JSON válido con versión desconocida: se saltea igual que una línea rota.
        Path(S.SESIONES.mapa_ruta).write_text(
            json.dumps({"v": 999, "clave": "del-futuro", "sesion_id": "x", "ts": 1}) + "\n"
            + json.dumps({"v": S.MAPA_V, "clave": "buena", "sesion_id": "y",
                          "ts": __import__("time").time()}) + "\n", encoding="utf-8")
        reiniciar_proceso()
        S.SESIONES.cargar()
        check("V4 una `v` desconocida se saltea y NO contamina lo bueno",
              S.SESIONES.obtener("del-futuro", "claude_cli").restaurada is False
              and S.SESIONES.obtener("buena", "claude_cli").id == "y",
              str(S.SESIONES.estado()["mapa"]))

        # y el ARRANQUE de verdad —el que bindea— no revienta con el archivo roto
        Path(S.SESIONES.mapa_ruta).write_bytes(b"\x00\x01\x02 no soy json")
        reiniciar_proceso()
        try:
            srv2 = create_server(0)
            srv2.server_close()
            arrancó = True
            detalle = ""
        except Exception as e:                      # noqa: BLE001
            arrancó, detalle = False, f"{type(e).__name__}: {e}"
        check("V4 el arranque del server NO se cae con el mapa roto", arrancó, detalle)

        # ══ V5 · LA ESCRITURA ATÓMICA ══════════════════════════════════════════════
        seccion("V5 · escritura atómica → una interrupción deja el archivo PREVIO entero")
        S.SESIONES.reiniciar()
        buena = S.SESIONES.obtener("vara-obra4-atomica", "claude_cli")
        plantar_transcript(buena.id, buena.workdir)
        S.SESIONES.recordar(buena)
        sha_bueno = sha_del_mapa()
        bytes_buenos = Path(S.SESIONES.mapa_ruta).read_bytes()
        check("V5 punto de partida: el mapa tiene la fila buena",
              len(filas_del_mapa()) == 1 and bool(sha_bueno), str(filas_del_mapa()))

        otra = S.SESIONES.obtener("vara-obra4-atomica-2", "claude_cli")
        plantar_transcript(otra.id, otra.workdir)

        def _explota(*_a, **_k):
            raise OSError(28, "simulación: se cortó a mitad de escribir")

        for nombre, atributo in (("fsync (los bytes ya estaban en el .tmp)", "fsync"),
                                 ("replace (el rename atómico)", "replace")):
            original = getattr(S.os, atributo)
            setattr(S.os, atributo, _explota)
            try:
                escribió = S.SESIONES.recordar(otra)
                reventó = ""
            except Exception as e:                  # noqa: BLE001
                escribió, reventó = None, f"{type(e).__name__}: {e}"
            finally:
                setattr(S.os, atributo, original)
            check(f"V5 corte en {nombre} → False, sin excepción",
                  escribió is False and not reventó, f"devolvió={escribió} {reventó!r}")
            check(f"V5 corte en {nombre} → el archivo PREVIO sigue byte-idéntico",
                  Path(S.SESIONES.mapa_ruta).read_bytes() == bytes_buenos
                  and sha_del_mapa() == sha_bueno, f"sha={sha_del_mapa()[:12]}")
            check(f"V5 corte en {nombre} → no queda un `.tmp` a medias",
                  not Path(S.SESIONES.mapa_ruta + ".tmp").exists(),
                  S.SESIONES.mapa_ruta + ".tmp")

        reiniciar_proceso()
        check("V5 y una instancia NUEVA lo lee entero después del corte",
              S.SESIONES.cargar() == 1
              and S.SESIONES.obtener("vara-obra4-atomica", "claude_cli").id == buena.id,
              str(filas_del_mapa()))

        # sin el corte, la escritura sí ocurre — para que V5 no sea verde por no escribir
        S.SESIONES.reiniciar()
        b2 = S.SESIONES.obtener("vara-obra4-atomica", "claude_cli")
        plantar_transcript(b2.id, b2.workdir)
        check("V5 (control) sin corte, la MISMA llamada sí escribe",
              S.SESIONES.recordar(b2) is True and len(filas_del_mapa()) == 1,
              str(filas_del_mapa()))
    finally:
        _detect._BY_MODEL_ID.clear()
        _detect._BY_MODEL_ID.update(guardado)
        srv.shutdown()
        srv.server_close()
        SL.SLOTS.reiniciar()

    # ══ V6 · LA MEMORIA TALADRO ════════════════════════════════════════════════════
    # Las hijas corren con el entorno LIMPIO: sin `CLAUDE_CONFIG_DIR` no pierden el auth
    # del CLI y su parte viva mide de verdad en vez de saltearse.
    seccion("V6 · la memoria TALADRO sigue viva — la vara de F2e, contra el CLI real")
    hija = subprocess.run(
        [sys.executable, str(HERE / "cli_brain" / "verify_cli_sesiones.py")],
        cwd=str(ROOT), text=True, capture_output=True, env=env_limpio())
    salida_f2e = hija.stdout + hija.stderr
    check("V6 verify_cli_sesiones.py (F2e) verde", hija.returncode == 0,
          (salida_f2e.strip().splitlines() or [""])[-1])
    check("V6 y midió el TALADRO de verdad: el turno 2 recordó el turno 1",
          "EL SEGUNDO TURNO RECUERDA EL PRIMERO" in salida_f2e
          and "⊘ los dos turnos contra el CLI real" not in salida_f2e,
          "sección 7 salteada" if "⊘ los dos turnos" in salida_f2e else "medida")
    check("V6 y el ahorro incremental sigue en pie",
          "el annex dice que se mandó SÓLO lo nuevo" in salida_f2e
          and "✗" not in salida_f2e,
          [l for l in salida_f2e.splitlines() if l.strip().startswith("✗")][:3])

    # ══ V7 · LA REGRESIÓN ══════════════════════════════════════════════════════════
    seccion("V7 · regresión — las varas de las obras anteriores y de Gate 1/F4a")
    comandos = [
        ("Obra 1 22/22", [sys.executable, str(HERE / "verify_costura_obra1.py")]),
        ("Obra 2 remapeada", [sys.executable, str(HERE / "verify_costura_obra2.py")]),
        ("Obra 3 scrub+D7", [sys.executable, str(HERE / "verify_costura_obra3.py")]),
        ("Gate 1 4/4", [sys.executable, "-m", "pytest", "-q",
                        "platform/assembler/test_gate_in_path.py"]),
        ("verify_f4a (28 motor / 26 traductor)",
         [sys.executable, str(HERE / "verify_f4a.py")]),
        ("F4d · el slug que no encontraba sus sesiones",
         [sys.executable, str(HERE / "cli_brain" / "verify_f4d.py")]),
    ]
    for etiqueta, comando in comandos:
        hecho = subprocess.run(comando, cwd=str(ROOT), text=True, capture_output=True,
                               env=env_limpio())
        cola = (hecho.stdout + hecho.stderr).strip().splitlines()[-1:]
        check(f"V7 {etiqueta} verde", hecho.returncode == 0, cola)

    # ══ [H3 · EL CASO ÍNDICE] LA ÚLTIMA LÍNEA ES EL VEREDICTO ═════════════════════════
    # Acá esta nota iba DESPUÉS del resumen. Un `tail -1` leyó «(la saneada completa …)»
    # en vez de «=== N passed, M failed ===» y casi aborta un merge sano. La nota no
    # sobra —dice algo cierto— pero va arriba: lo último que imprime una vara es su
    # veredicto, siempre.
    print(f"    (la saneada completa `qa/correr_varas.py` NO la corre esta vara: es la "
          f"corrida de pre-merge, y va aparte en el reporte)")
    print(f"\n=== {PASSED} passed, {FAILED} failed ===")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
