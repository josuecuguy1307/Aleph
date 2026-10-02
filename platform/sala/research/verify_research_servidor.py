"""verify_research_servidor.py — LA VARA DEL VERDE MUDO. [Gate 4 · Fase 6 · §6.f]

    <python> platform/sala/research/verify_research_servidor.py
    <python> platform/sala/research/verify_research_servidor.py --caer

QUÉ MIDE, Y POR QUÉ ESE Y NO OTRO
----------------------------------
La búsqueda web encontró hoy el peor modo de fallo posible: **el turno terminaba en 200,
sin error, con una respuesta cortés sobre resultados vacíos**. Un verde mudo. El
equivalente en deep research es peor todavía, porque el producto de este modo *es* un
informe con fuentes: si sale un informe **con 200 y cero fuentes**, o **con menos etapas
de las que dice haber corrido**, el usuario recibe prosa fabricada con cara de
investigación.

`arranque.sh:70-73` ya nombra ese miedo por escrito («la Sala pintaría progreso y
entregaría un informe sin fuentes con cara de éxito»), y `etapas.py:196-206` ya lo atrapa
**en el latido** —el `{"phase":"synthesis","type":"error"}` de `source_based_strategy.py:492`
se pinta como FALLANDO—. Lo que faltaba medir es **el desenlace**: qué sobre sale al final.

EL MOTOR ES UN DOBLE, Y ESO ES LO CORRECTO
-------------------------------------------
Esta vara **no** mide si Local Deep Research investiga bien: eso lo mide correr el motor
(medido aparte: importa, y el servidor contesta `/health`). Mide el **contrato del
servidor de la casa** ante un motor que devuelve basura, y para eso el motor tiene que
ser determinista. Se inyecta un `local_deep_research` de mentira **por delante** de
`third_party/ldr/src` en el `PYTHONPATH`, y el que corre es el `servidor.py` de verdad,
sin un solo parche: proceso real, puerto real, NDJSON real.

QUE UN CRASH NO CUENTE COMO CAÍDA
----------------------------------
Un caso sin líneas NDJSON no es un rojo: es `[no medible]`. Si el servidor murió, el
stub no arrancó, o el puerto no atendió, la vara lo dice con motivo y **no** lo cuenta
como que la propiedad se cumplió ni como que falló. Es la lección de las 8 mutaciones
verdes sobre una vara rota.

LA PRUEBA DE CAÍDA — `--caer`
------------------------------
Con `--caer` el doble del motor se comporta **bien** en los casos del verde mudo (informe
con fuentes de verdad, y las etapas que dice). Las aserciones que atrapan el verde mudo
tienen que **dejar de cumplirse por falta de disparador** y salir marcadas
`[caída]`: una vara que da lo mismo con el defecto y sin él no mide nada.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

_AQUI = Path(__file__).resolve().parent
_RAIZ = _AQUI.parent.parent.parent

#: De dónde sale el `servidor.py` que se levanta. Es el del árbol salvo en `--mutar`.
_PACK = _AQUI

_OK: list[str] = []
_MAL: list[str] = []
_NM: list[str] = []


def _p(nombre: str, cond: bool, detalle: str = "") -> bool:
    (_OK if cond else _MAL).append(nombre)
    print(f"[{'PASS' if cond else 'FAIL'}] {nombre}" + (f" — {detalle}" if detalle else ""))
    return cond


def _nm(nombre: str, motivo: str) -> None:
    """La ausencia de una señal no es una medición."""
    _NM.append(nombre)
    print(f"[no medible] {nombre} — {motivo}")


def _pd(nombre: str, cond: bool, sano: bool, detalle: str = "") -> bool:
    """Aserción que **necesita el defecto** para poder cumplirse.

    Ésta es la distinción que la primera versión de esta vara no hacía, y por eso su prueba
    de caída marcaba `[caída]` sobre aserciones que pasaban igual con el motor sano. Hay
    dos clases de aserción y confundirlas es lo que deja una vara sin poder dar rojo:

      · **seguridad** (`_p`) — «un informe sin fuentes NO se entrega como bueno». Vale
        siempre. Con el motor sano se cumple **por falta de sujeto**, y eso está bien: es
        una propiedad, no una medición. Marcarla `[caída]` sería mentir.

      · **disparador** (`_pd`) — «sale la causa `informe_sin_fuentes`». Sólo puede
        cumplirse si el defecto está presente. Con `--caer` el defecto no está, así que
        **cumplirse sería el rojo**: querría decir que la causa sale sin motivo.

    Con motor enfermo se exige `cond`. Con motor sano se exige `not cond`.
    """
    esperado = (not cond) if sano else cond
    etiqueta = f"[caída] sólo se cumple con el defecto · {nombre}" if sano else nombre
    (_OK if esperado else _MAL).append(etiqueta)
    print(f"[{'PASS' if esperado else 'FAIL'}] {etiqueta}" + (f" — {detalle}" if detalle else ""))
    return esperado


# ── el doble del motor ────────────────────────────────────────────────────────
#
# Se escribe a disco en un dir temporal propio y se pone PRIMERO en el PYTHONPATH. El
# `servidor.py` importa `local_deep_research` de forma perezosa (`servidor.py:325`), así
# que resuelve contra esto y no contra `third_party/ldr/src`.

_STUB_LDR = r'''
import json, os, time
_CASO = os.environ.get("VARA_CASO", "")
_SANO = os.environ.get("VARA_SANO") == "1"
_HUELLA = os.environ.get("VARA_HUELLA", "")

def _anotar(clave, valor):
    if not _HUELLA:
        return
    with open(_HUELLA, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({clave: valor}) + "\n")
'''

_STUB_API = r'''
import os, time
from local_deep_research import _anotar, _CASO, _SANO
from local_deep_research.exceptions import ResearchTerminatedException

_FUENTES_REALES = [
    {"url": "https://es.wikipedia.org/wiki/Fotosintesis", "title": "Fotosíntesis"},
    {"url": "https://arxiv.org/abs/2401.00001", "title": "Light harvesting"},
]

def _latir(cb, fase, msg, pct=None, extra=None):
    meta = {"phase": fase}
    if extra:
        meta.update(extra)
    if cb:
        cb(msg, pct, meta)

def _correr(query, **kw):
    cb = kw.get("progress_callback")
    _anotar("llamada", {"query": query, "tiene_llm": bool(kw.get("llms")),
                        "snapshot": bool(kw.get("settings_snapshot")),
                        "programmatic": kw.get("programmatic_mode")})

    if _CASO == "cancelacion":
        # El motor largo: late hasta que alguien lo pare. Los puntos de chequeo del motor
        # de verdad viven en `base_strategy.py:99-131`; acá se reproduce el mismo ritmo.
        for i in range(200):
            _latir(cb, "search", "buscando", None, {"iteration": i + 1})
            _anotar("latido", i + 1)
            time.sleep(0.05)
        _anotar("nunca_paro", True)
        return {"summary": "no me pararon", "sources": _FUENTES_REALES, "iterations": 200}

    # ⚠️ ESTE GUION SE MIDIÓ CONTRA EL MOTOR REAL, y cambiarlo costó un falso positivo.
    #
    # La primera versión emitía `search` y `source_gathering` —yo los inventé leyendo la
    # tabla de `etapas.py`— y con eso el fixture traía una pista que el motor de verdad NO
    # DA. Medido sobre dos obras reales contra un SearXNG real, las únicas fases que el
    # callback emite son: `setup · init · question_generation · final_filtering ·
    # filtering_complete · synthesis`. **Ninguna es de búsqueda**: el motor busca sin
    # anunciarlo, y volvió con 30 fuentes.
    #
    # Por culpa de esa pista, esta vara daba verde sobre un `servidor.py` que rechazaba
    # TODA investigación buena con `investigacion_sin_busqueda`. Un fixture que sabe la
    # respuesta no mide nada — es la misma lección que la búsqueda web pagó con el suyo.
    _latir(cb, "setup", "arrancando", 1)
    _latir(cb, "init", "iniciando", 5, {"max_iterations": 3})
    if _SANO or _CASO != "sin_fuentes_utiles":
        _latir(cb, "question_generation", "armando preguntas", 20)
        _latir(cb, "final_filtering", "filtrando", 60)
        _latir(cb, "filtering_complete", "filtradas", 70)
    _latir(cb, "synthesis", "sintetizando", 90)

    if _SANO:
        return {"summary": "Un informe de verdad.", "sources": _FUENTES_REALES, "iterations": 3}

    if _CASO == "sin_fuentes":
        # El caso EXACTO de `source_based_strategy.py:492`: dice que terminó, y no trae
        # una sola fuente.
        return {"summary": "La fotosíntesis es el proceso por el cual las plantas…",
                "sources": [], "iterations": 3}
    if _CASO == "fuentes_fantasma":
        # 10 «fuentes» que ninguna sobrevive a la normalización: `_fuentes()` las tira una
        # por una y devuelve []. Desde afuera es indistinguible de `sin_fuentes`, y ahí
        # está el punto: el motor DIJO diez.
        return {"summary": "Texto con cara de informe.",
                "sources": [None, 12, {"nombre": "sin url"}, "", "   ", {}, [], 0, False, {"url": ""}],
                "iterations": 3}
    if _CASO == "obra_buena":
        # Una investigación SANA: el motor no anunció búsquedas —como el real— y volvió
        # con fuentes. Tiene que cruzar.
        return {"summary": "Un informe con fuentes de verdad.",
                "sources": _FUENTES_REALES, "iterations": 3}
    return {"summary": "ok", "sources": _FUENTES_REALES, "iterations": 1}

def quick_summary(query, **kw):
    return _correr(query, **kw)

def detailed_research(query, **kw):
    return _correr(query, **kw)
'''

_STUB_SETTINGS = r'''
def create_settings_snapshot(overrides=None, **kw):
    return dict(overrides or {})
'''

_STUB_EXC = r'''
class ResearchTerminatedException(BaseException):
    """Igual que la de ellos: hereda de BaseException a propósito."""
'''

_STUB_LLM = r'''
_REG = {}
def register_llm(nombre, llm=None, **kw):
    _REG[nombre] = llm
def unregister_llm(nombre):
    from local_deep_research import _anotar
    _anotar("unregister", nombre)
    _REG.pop(nombre, None)
def is_llm_registered(nombre):
    return nombre in _REG
'''

# `cerebro.construir()` importa `langchain_openai`. Es el SDK de verdad y pesa 1,9 GiB de
# árbol de dependencias; la vara no lo necesita para medir el contrato del servidor, así
# que también viaja doblado — y el doble ANOTA sus cabeceras, que es lo que hace medible
# que `X-Aleph-Space` viajó.
_STUB_LANGCHAIN = r'''
from local_deep_research import _anotar

class ChatOpenAI:
    def __init__(self, **kw):
        self.kw = kw
        _anotar("chat_openai", {"base_url": kw.get("base_url"),
                                "headers": kw.get("default_headers") or {},
                                "max_retries": kw.get("max_retries")})
'''


def _plantar_stub(raiz: Path) -> None:
    ldr = raiz / "local_deep_research"
    (ldr / "api").mkdir(parents=True, exist_ok=True)
    (ldr / "llm").mkdir(parents=True, exist_ok=True)
    (ldr / "__init__.py").write_text(_STUB_LDR, encoding="utf-8")
    (ldr / "api" / "__init__.py").write_text(_STUB_API, encoding="utf-8")
    (ldr / "api" / "settings_utils.py").write_text(_STUB_SETTINGS, encoding="utf-8")
    (ldr / "exceptions.py").write_text(_STUB_EXC, encoding="utf-8")
    (ldr / "llm" / "__init__.py").write_text(_STUB_LLM, encoding="utf-8")
    lc = raiz / "langchain_openai"
    lc.mkdir(parents=True, exist_ok=True)
    (lc / "__init__.py").write_text(_STUB_LANGCHAIN, encoding="utf-8")


def _puerto_libre() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class _Servidor:
    """El `servidor.py` DE VERDAD, en un proceso propio, con el motor doblado."""

    def __init__(self, base: Path, caso: str, *, sano: bool):
        self.base = base
        self.caso = caso
        self.sano = sano
        self.puerto = _puerto_libre()
        self.huella = base / f"huella-{caso}.jsonl"
        self.log = base / f"servidor-{caso}.log"
        self.proc: Optional[subprocess.Popen] = None

    def __enter__(self) -> "_Servidor":
        cfg = self.base / "cfg"
        cfg.mkdir(parents=True, exist_ok=True)
        (cfg / "aleph-cerebro.json").write_text(json.dumps({
            "provider": {"aleph": {"options": {
                "baseURL": "http://127.0.0.1:9/v1/workspaces/brain/openai",
                "apiKey": "",
                "headers": {"X-Aleph-Workspace": "sala_research"}}}},
            "model": "aleph/cerebro"}), encoding="utf-8")
        env = dict(os.environ)
        env.update({
            # El doble PRIMERO: es lo que hace que el servidor real corra contra un motor
            # determinista sin tocarle una línea.
            "PYTHONPATH": f"{self.base / 'stub'}:{_RAIZ / 'third_party' / 'ldr' / 'src'}",
            "ALEPH_RESEARCH_CONFIG_DIR": str(cfg),
            "LDR_DATA_DIR": str(self.base / "datos"),
            # El buscador se declara para pasar la puerta de `sin_buscador`: lo que este
            # caso mide está DESPUÉS de esa puerta.
            "ALEPH_SEARXNG_URL": "http://127.0.0.1:1/",
            "VARA_CASO": self.caso,
            "VARA_SANO": "1" if self.sano else "0",
            "VARA_HUELLA": str(self.huella),
            "PYTHONUNBUFFERED": "1",
        })
        self.proc = subprocess.Popen(
            [sys.executable, str(_PACK / "servidor.py"), "--port", str(self.puerto)],
            env=env, stdout=self.log.open("wb"), stderr=subprocess.STDOUT)
        for _ in range(80):
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{self.puerto}/health", timeout=1) as r:
                    if r.status == 200:
                        return self
            except (urllib.error.URLError, OSError):
                time.sleep(0.1)
        return self

    def __exit__(self, *a) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def vivo(self) -> bool:
        return bool(self.proc) and self.proc.poll() is None

    def investigar(self, consulta: str, *, timeout: float = 30.0,
                   modo: str = "resumen", iteraciones: Optional[int] = None) -> list[dict]:
        """Devuelve las líneas NDJSON parseadas. Lista vacía = no hubo señal."""
        cuerpo = {"query": consulta, "modo": modo}
        if iteraciones:
            cuerpo["iteraciones"] = iteraciones
        pedido = urllib.request.Request(
            f"http://127.0.0.1:{self.puerto}/research",
            data=json.dumps(cuerpo).encode(), method="POST",
            headers={"Content-Type": "application/json"})
        lineas: list[dict] = []
        try:
            with urllib.request.urlopen(pedido, timeout=timeout) as r:
                for cruda in r:
                    cruda = cruda.strip()
                    if cruda:
                        lineas.append(json.loads(cruda))
        except Exception:                                          # noqa: BLE001
            pass
        return lineas

    def cancelar(self, obra_id: str) -> dict:
        pedido = urllib.request.Request(
            f"http://127.0.0.1:{self.puerto}/cancelar",
            data=json.dumps({"obra_id": obra_id}).encode(), method="POST",
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(pedido, timeout=5) as r:
            return json.loads(r.read().decode())

    def huellas(self) -> list[dict]:
        if not self.huella.exists():
            return []
        return [json.loads(x) for x in self.huella.read_text(encoding="utf-8").splitlines() if x.strip()]


def _de_tipo(lineas: list[dict], tipo: str) -> list[dict]:
    return [x for x in lineas if x.get("tipo") == tipo]


def _cola(log: Path, n: int = 6) -> str:
    try:
        return " / ".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-n:])
    except OSError:
        return "(sin log)"


# ── los casos ─────────────────────────────────────────────────────────────────

def _caso_sin_fuentes(base: Path, sano: bool) -> None:
    marca = "[motor sano] " if sano else ""
    with _Servidor(base, "sin_fuentes", sano=sano) as s:
        if not s.vivo():
            _nm(f"{marca}A el informe sin fuentes NO sale como éxito",
                f"el servidor no arrancó: {_cola(s.log)}")
            return
        lineas = s.investigar("qué es la fotosíntesis")
        if not lineas:
            _nm(f"{marca}A el informe sin fuentes NO sale como éxito",
                f"cero líneas NDJSON — el servidor no habló: {_cola(s.log)}")
            return
        informes = _de_tipo(lineas, "informe")
        fallos = _de_tipo(lineas, "fallo")
        # LA PROPIEDAD. Un informe con cero fuentes NO puede salir como `informe`: eso es
        # el 200 cortés sobre el vacío.
        _p("A1 un informe con CERO fuentes no se entrega como `informe`",
           not any(not (i.get("fuentes") or []) for i in informes),
           f"informes={[len(i.get('fuentes') or []) for i in informes]}")
        _pd("A2 …y sale una causa tipada que la Sala puede pintar",
            any(f.get("causa") == "informe_sin_fuentes" for f in fallos), sano,
            f"causas={[f.get('causa') for f in fallos]}")
        _pd("A3 …con su copy (ninguna causa llega a una superficie sin copy)",
            bool(fallos) and all((f.get("copy") or "").strip() for f in fallos), sano,
            f"copys={[f.get('copy') for f in fallos]}")
        # Esto SÍ tiene que valer siempre: el turno cierra pase lo que pase.
        _p("A4 el turno CIERRA igual (ni con el informe vacío queda colgado)",
           len(_de_tipo(lineas, "cierra")) == 1)
        # El sobre del fallo tiene que traer el borrador. Si el modo tirara el texto, el
        # usuario perdería minutos de modelo por una fuente que no vino.
        _p("A5 el texto producido NO se tira: viaja adentro del fallo",
           any("fotosíntesis" in str(f.get("texto") or "").lower() for f in fallos)
           if not sano else all(bool(i.get("texto")) for i in informes) and bool(informes),
           f"textos={[str(x.get('texto') or '')[:30] for x in (fallos or informes)]}")


def _caso_fuentes_fantasma(base: Path, sano: bool) -> None:
    marca = "[motor sano] " if sano else ""
    with _Servidor(base, "fuentes_fantasma", sano=sano) as s:
        if not s.vivo():
            _nm(f"{marca}B las fuentes que no sobreviven se declaran",
                f"el servidor no arrancó: {_cola(s.log)}")
            return
        lineas = s.investigar("qué es la fotosíntesis")
        if not lineas:
            _nm(f"{marca}B las fuentes que no sobreviven se declaran",
                f"cero líneas NDJSON: {_cola(s.log)}")
            return
        sobres = _de_tipo(lineas, "informe") + _de_tipo(lineas, "fallo")
        # El motor dijo DIEZ y sobrevivió CERO. Que el número crudo se diga es lo que
        # separa «no encontró nada» de «encontró basura», que son dos bugs distintos.
        _pd("B1 se declara CUÁNTAS fuentes dijo el motor, no sólo las que sirvieron",
            any(x.get("fuentes_crudas") == 10 for x in sobres), sano,
            f"crudas={[x.get('fuentes_crudas') for x in sobres]}")
        _p("B2 diez fuentes ilegibles no se entregan como informe bueno",
           not any(x.get("tipo") == "informe" and not (x.get("fuentes") or [])
                   for x in sobres))
        _p("B3 el turno CIERRA", len(_de_tipo(lineas, "cierra")) == 1)


def _caso_obra_buena_no_se_rechaza(base: Path, sano: bool) -> None:
    """La contracara del verde mudo, y la que faltaba: **el falso positivo.**

    Acá vivía un caso que medía «el motor no emitió una etapa de búsqueda → se rechaza».
    Esa puerta se sacó del `servidor.py` porque rechazaba TODA investigación buena: el
    motor real busca sin anunciarlo y la obra volvía con 30 fuentes igual. El caso se
    reescribe apuntando al hecho que sí importa —que un informe con fuentes CRUZA— porque
    una vara que sólo sabe encontrar de más es media vara.
    """
    with _Servidor(base, "obra_buena", sano=True) as s:
        if not s.vivo():
            _nm("C una obra con fuentes NO se rechaza", f"el servidor no arrancó: {_cola(s.log)}")
            return
        lineas = s.investigar("qué es la fotosíntesis", iteraciones=3)
        if not lineas:
            _nm("C una obra con fuentes NO se rechaza", f"cero líneas NDJSON: {_cola(s.log)}")
            return
        informes = _de_tipo(lineas, "informe")
        fallos = _de_tipo(lineas, "fallo")
        etapas_vistas = {e.get("etapa") for e in _de_tipo(lineas, "estado")}
        # EL DISPARADOR: el motor NO emitió una etapa de búsqueda — igual que el real.
        _p("C0 el motor no anuncia sus búsquedas (como el real: medido)",
           "buscando" not in etapas_vistas, f"etapas={sorted(x for x in etapas_vistas if x)}")
        _p("C1 …y AUN ASÍ el informe con fuentes se entrega, no se rechaza",
           len(informes) == 1 and not fallos,
           f"informes={len(informes)} fallos={[f.get('causa') for f in fallos]}")
        _p("C2 el sobre final declara las etapas REALMENTE corridas (dato, no veredicto)",
           all(isinstance(x.get("etapas"), list) for x in informes),
           f"etapas={[x.get('etapas') for x in informes]}")


def _caso_cancelacion(base: Path, sano: bool) -> None:
    """La condición dura de §6.f: un botón de parar que no para es peor que no tenerlo.

    El `abre` se lee INCREMENTAL. Consumir el stream entero antes de cancelar mediría el
    `no_habia_turno`, que es otro caso: para cancelar algo hay que tener su id mientras
    todavía corre."""
    with _Servidor(base, "cancelacion", sano=sano) as s:
        if not s.vivo():
            _nm("D la cancelación PARA el motor", f"el servidor no arrancó: {_cola(s.log)}")
            return
        pedido = urllib.request.Request(
            f"http://127.0.0.1:{s.puerto}/research",
            data=json.dumps({"query": "una investigación larga"}).encode(), method="POST",
            headers={"Content-Type": "application/json"})
        lineas: list[dict] = []
        try:
            r = urllib.request.urlopen(pedido, timeout=60)
        except Exception as e:                                     # noqa: BLE001
            _nm("D la cancelación PARA el motor", f"el stream no abrió: {e}")
            return
        primera = r.readline().strip()
        if not primera:
            _nm("D la cancelación PARA el motor", f"cero líneas: {_cola(s.log)}")
            return
        abre = json.loads(primera)
        lineas.append(abre)
        obra_id = abre.get("obra_id")
        # Esperar a que el motor esté REALMENTE corriendo: sin latidos no hay nada que
        # parar y el caso mediría otra cosa.
        for _ in range(100):
            if len([h for h in s.huellas() if "latido" in h]) >= 3:
                break
            time.sleep(0.1)
        else:
            _nm("D la cancelación PARA el motor", "el motor nunca latió")
            return
        latidos_al_cancelar = len([h for h in s.huellas() if "latido" in h])
        t0 = time.monotonic()
        resp = s.cancelar(str(obra_id))
        for cruda in r:
            cruda = cruda.strip()
            if cruda:
                lineas.append(json.loads(cruda))
        ms = int((time.monotonic() - t0) * 1000)
        hs = s.huellas()
        latidos_final = len([h for h in hs if "latido" in h])

        _p("D0 el disparador estuvo: había una obra viva para cancelar",
           bool(resp.get("encontrada")), f"respuesta={resp}")
        _p("D1 el motor SE PARÓ de verdad (dejó de latir), no sólo dejó de pintarse",
           latidos_final < 200 and not any("nunca_paro" in h for h in hs),
           f"latidos {latidos_al_cancelar}→{latidos_final} de 200 posibles")
        _p("D2 el turno termina con la causa `obra_cancelada`, no con un corte anónimo",
           any(f.get("causa") == "obra_cancelada" for f in _de_tipo(lineas, "fallo")),
           f"causas={[f.get('causa') for f in _de_tipo(lineas, 'fallo')]}")
        _p("D3 …con su copy", all((f.get("copy") or "").strip()
                                  for f in _de_tipo(lineas, "fallo")))
        _p("D4 parar tarda menos de 5 s (si tardara minutos, el botón sería teatro)",
           ms < 5000, f"{ms} ms")
        _p("D5 el registro queda limpio: cancelar de nuevo dice que no había turno",
           not s.cancelar(str(obra_id)).get("encontrada"))
        _p("D6 el cliente de LDR se DESREGISTRA (el registro es global al proceso)",
           any("unregister" in h for h in hs), f"huellas={[list(h)[0] for h in hs[-4:]]}")


def _caso_costura(base: Path, sano: bool) -> None:
    """LEY 12: el cerebro que viaja es el de la casa, y el espacio viaja con él."""
    with _Servidor(base, "costura", sano=True) as s:
        if not s.vivo():
            _nm("E la costura del cerebro", f"el servidor no arrancó: {_cola(s.log)}")
            return
        lineas = s.investigar("una consulta cualquiera")
        hs = s.huellas()
        chat = next((h["chat_openai"] for h in hs if "chat_openai" in h), None)
        llam = next((h["llamada"] for h in hs if "llamada" in h), None)
        if chat is None or llam is None:
            _nm("E la costura del cerebro",
                f"el motor doble nunca fue llamado: {_cola(s.log)}")
            return
        abre = next(iter(_de_tipo(lineas, "abre")), {})
        _p("E1 el cerebro apunta al BORDE de la casa, no a un proveedor",
           "/v1/workspaces/brain/openai" in str(chat.get("base_url")), str(chat.get("base_url")))
        _p("E2 `X-Aleph-Space` viaja: sin él el anti-grift queda ciego a este modo",
           (chat.get("headers") or {}).get("X-Aleph-Space") == abre.get("espacio"),
           f"header={(chat.get('headers') or {}).get('X-Aleph-Space')} espacio={abre.get('espacio')}")
        _p("E3 sin reintentos del SDK (duplicarían turnos en el ledger)",
           chat.get("max_retries") == 0, f"max_retries={chat.get('max_retries')}")
        _p("E4 el modelo se inyecta por parámetro y el snapshot manda (cero corte al motor)",
           bool(llam.get("tiene_llm")) and bool(llam.get("snapshot")), str(llam))
        _p("E5 `programmatic_mode` explícito: cero base, cero métricas, cero identidad",
           llam.get("programmatic") is True, str(llam.get("programmatic")))


def _mutar(destino: Path) -> Path:
    """Una copia del pack con **las dos puertas del verde mudo arrancadas**.

    `--caer` prueba que las aserciones del disparador dejan de cumplirse sin el defecto.
    Esto prueba lo otro, que es lo que de verdad hace que una vara sirva: **que da rojo
    cuando el arreglo no está**. Sin este modo, la única evidencia de que mide algo sería
    haberla corrido una vez antes del arreglo — un hecho del pasado que nadie puede
    repetir.

    La mutación es quirúrgica: se le sacan las dos líneas que levantan `_InformeMudo` y
    nada más. Todo lo demás —contabilidad de etapas, `fuentes_crudas`, causas, copy— queda
    en pie, así que lo que caiga cae por la puerta que falta y no por un archivo roto.
    """
    destino.mkdir(parents=True, exist_ok=True)
    for nombre in ("servidor.py", "cerebro.py", "etapas.py"):
        shutil.copy2(_AQUI / nombre, destino / nombre)
    srv = destino / "servidor.py"
    texto = srv.read_text(encoding="utf-8")
    PUERTAS = (
        '        if not fuentes:\n'
        '            raise _InformeMudo("informe_sin_fuentes", salida)\n',
    )
    for puerta in PUERTAS:
        if puerta not in texto:
            raise SystemExit(
                'vara: la mutación no encontró la puerta que iba a arrancar. El arreglo '
                'cambió de forma y esta vara dejó de medirlo — arreglar la vara, no el '
                'veredicto.')
        texto = texto.replace(puerta, '')
    srv.write_text(texto, encoding="utf-8")
    return destino


def main(argv: list[str]) -> int:
    caer = "--caer" in argv
    mutar = "--mutar" in argv
    if caer and mutar:
        raise SystemExit("vara: --caer y --mutar miden cosas distintas; no se combinan.")
    base = Path(tempfile.mkdtemp(prefix="vara-research-"))
    try:
        _plantar_stub(base / "stub")
        global _PACK
        if mutar:
            _PACK = _mutar(base / "mutante")
        titulo = ("CAÍDA (motor sano)" if caer else
                  "MUTANTE (sin la puerta)" if mutar else "motor enfermo")
        print(f"=== vara del verde mudo · {titulo} ===")
        print(f"    tmp={base}\n")
        _caso_sin_fuentes(base, caer)
        _caso_fuentes_fantasma(base, caer)
        _caso_obra_buena_no_se_rechaza(base, caer)
        if not caer:
            # La cancelación y la costura no tienen «versión sana»: son propiedades que
            # deben cumplirse siempre, así que en el modo caída no se re-miden.
            _caso_cancelacion(base, caer)
            _caso_costura(base, caer)
        print(f"\n=== {len(_OK)} passed, {len(_MAL)} failed, {len(_NM)} no medibles ===")
        if mutar:
            # Sin la puerta, esta vara TIENE que dar rojo. Un mutante todo en verde
            # significa que la vara no mide lo que dice medir, y eso es peor que un rojo.
            if _NM:
                print("\n>>> MUTANTE NO MEDIBLE: la copia mutada no corrió. No prueba nada.")
                return 1
            print(f"\n>>> el mutante dio {len(_MAL)} rojas: la vara SÍ mide el arreglo."
                  if _MAL else
                  "\n>>> MUTANTE TODO EN VERDE: esta vara no mide el arreglo. Rota.")
            return 0 if _MAL else 1
        return 1 if (_MAL or _NM) else 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
