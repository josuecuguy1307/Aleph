"""arnes_suite.py — EL MOLDE DE LOS CUATRO ARNESES de `DISEÑO-SUITE-v1.md` §3·bis.

S2 escribió el molde dentro de `verify_llave_stdio.py`. S3 tenía que hacer «lo mismo con
otro ejemplar» tres veces más, y copiarlo cuatro veces habría matado la ley que la §3·bis
protege: **si cada arnés tiene su propia copia del contrato, el contrato del tipo vuelve a
estar repartido en N archivos que se parecen** — que es exactamente el daño que la ley
existe para evitar, sólo que un nivel más arriba.

Así que el molde vive UNA vez, acá, y cada arnés declara lo suyo:

    TIPO              cómo se llama el tipo de conexión
    EJEMPLAR_DEFECTO  quién lo encarna HOY (un parámetro, jamás la identidad)
    VERBOS            los 12, con su clase para ESE tipo y su motivo

**Esto NO es una vara y por eso no se llama `verify_…`**: no tiene veredicto propio ni se
corre solo. Es la biblioteca que los cuatro arneses usan.

LAS CUATRO CLASES DE VEREDICTO, que son el corazón de todo esto:

    EJERCITADO  lo prueba ESE arnés, acá, ahora
    DELEGADO    ya lo cubre otra vara — y se verifica QUE ESA VARA EXISTA, con su ruta
    NO_APLICA   el verbo no tiene sentido para ese TIPO (no para ese conector)
    DE_USUARIO    necesita un humano; el robot verifica lo que queda DESPUÉS

Un arnés que dijera «12/12 verde» estaría mintiendo sobre los tres verbos con parte humana
(§2), y ese verde falso es exactamente lo que esta serie viene cerrando.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "platform", ROOT / "platform" / "inspection",
           ROOT / "platform" / "assembler"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

EJERCITADO, DELEGADO, NO_APLICA, DE_USUARIO = "EJERCITADO", "DELEGADO", "NO_APLICA", "DE_USUARIO"
CLASES = (EJERCITADO, DELEGADO, NO_APLICA, DE_USUARIO)


class Arnes:
    """Un arnés de tipo. Lleva sus fallos y sabe correr las secciones del molde."""

    def __init__(self, tipo: str, ejemplar: str, verbos: list):
        self.tipo = tipo
        self.ejemplar = ejemplar
        self.verbos = verbos
        self.fallos: list = []
        self.notas: list = []

    # ── salida ──────────────────────────────────────────────────────────────────────
    def ok(self, cond, etiqueta, detalle=""):
        print(("  ✅ " if cond else "  ❌ ") + etiqueta + (f" · {detalle}" if detalle else ""))
        if not cond:
            self.fallos.append(etiqueta)
        return cond

    def nota(self, texto):
        """Un dato que NO es un fallo. Se imprime y se acumula para el cierre: lo que no se
        puede ejercitar hoy se DECLARA, no se esconde ni se cuenta como verde."""
        print(f"  ·  {texto}")
        self.notas.append(texto)

    # ── §0 · el reparto de los 12 ───────────────────────────────────────────────────
    def reparto(self):
        print("\n0 · el reparto de los 12 verbos (§2)")
        sin_clase = [n for n, _v, c, _r, _m in self.verbos if c not in CLASES]
        self.ok(not sin_clase, "los 12 tienen una clase declarada",
                str(sin_clase) if sin_clase else "")
        self.ok(len(self.verbos) == 12, "son DOCE, no once", f"{len(self.verbos)}")
        sin_motivo = [v for _n, v, _c, _r, m in self.verbos if not (m or "").strip()]
        self.ok(not sin_motivo, "y cada uno dice por qué",
                str(sin_motivo) if sin_motivo else "")

        # «Delegado» sin vara que exista es una promesa, no cobertura. Este chequeo cazó al
        # autor de S2 en la primera corrida: había delegado en un archivo inventado.
        huerfanos = [f"{v}→{r}" for _n, v, c, r, _m in self.verbos
                     if c == DELEGADO and not (ROOT / (r or "")).exists()]
        self.ok(not huerfanos, "cada verbo DELEGADO tiene su vara en disco",
                f"sin dueño: {huerfanos}" if huerfanos else
                f"{sum(1 for _n, _v, c, _r, _m in self.verbos if c == DELEGADO)} delegados, "
                f"todos vivos")

        reparto = {}
        for _n, v, c, _r, _m in self.verbos:
            reparto.setdefault(c, []).append(v)
        for c in CLASES:
            print(f"     {c:11} {len(reparto.get(c, [])):2} · {reparto.get(c, [])}")
        return reparto

    # ── la grabación ────────────────────────────────────────────────────────────────
    def grabacion(self) -> dict:
        """La receta del ejemplar sale de su GRABACIÓN y no de la DB.

        De la grabación a propósito: la DB es de esta máquina y de este usuario, así que un
        arnés que la leyera no correría en CI — que es justo lo que S1 vino a arreglar. La
        grabación es un fixture versionado y viaja con el commit."""
        import grabador as G
        d = ROOT / "platform" / "inspection" / "grabaciones" / self.ejemplar
        if not d.is_dir() or not list(d.glob("*.json")):
            print(f"\n⏸  no hay grabación de «{self.ejemplar}» en {d}")
            print(f"   Grabala primero:  {G.comando_para_regrabar(self.ejemplar)}")
            print("   (el driver real es `qa/grabar_ejemplar.py`, que graba por el mismo "
                  "camino que produce un veredicto)")
            sys.exit(2)
        pasos = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(d.glob("*.json"))]
        return {"dir": d, "meta": pasos[0], "pasos": pasos}

    # ── §1 · los EJERCITADOS, replayando ────────────────────────────────────────────
    def replay(self, grab: dict, *, espera_tools: bool = True, tool_extra=None):
        """Corre los verbos que este arnés ejercita, replayando: sin red y sin llaves.

        `espera_tools=False` es para un tipo cuya superficie depende de un consentimiento
        que hoy no está dado: ahí exigir «>0 tools» sería exigir que persona usuaria haya hecho su
        parte, y el arnés estaría rojo por algo que no es un defecto del código. La
        superficie vacía se DECLARA como nota y el veredicto del verbo baja a DE_USUARIO en
        la tabla — no se maquilla con una aserción que no puede fallar."""
        from inspection import transporte as TP
        import grabador as G                                          # noqa: F401

        meta = grab["meta"]
        print(f"\n1 · los EJERCITADOS, replayando «{self.ejemplar}» (sin red, sin llaves)")
        previo = os.environ.get("ALEPH_REPLAY")
        os.environ["ALEPH_REPLAY"] = self.ejemplar
        try:
            cls = TP.servidor_stdio()
            self.ok(getattr(cls, "envuelve", "") == "(replay · ningún proceso)",
                    "el transporte devolvió el REPLAY, no un cliente vivo",
                    getattr(cls, "envuelve", cls.__name__))

            # verbo 2 · prepare — el comando de la receta resuelve en esta máquina
            cmd = (meta.get("diagnostico", {}) or {}).get("command") or ""
            if not cmd:
                cmd = str((meta.get("receta") or {}).get("command") or "")
            base = (cmd.split() or [""])[0]
            resuelto = bool(shutil.which(base)) if base else False
            self.ok(bool(base),
                    f"prepare · el comando de la receta es nombrable ({base or '?'})",
                    "resuelve en el PATH" if resuelto else
                    "NO resuelve acá — y eso es dato, no fallo: instalarlo es de persona usuaria "
                    "(§2 verbo 2)")

            # El arnés es el consumidor de CI: NO conoce la receta —no hay DB de conexiones
            # acá— así que no la pasa y el replay usa la que guardó la grabación. Pasarle
            # una inventada sería pedirle a la DECISIÓN 1.C que valide contra una mentira.
            srv = cls(self.ejemplar, "", [], env=dict(os.environ))

            # verbo 4 · connect + verbo 5 · initialize
            self.ok(srv.start() is True,
                    "connect + initialize · el server arrancó (desde la grabación)")
            diag = srv.diagnostico() or {}
            si = diag.get("server_info") or {}
            self.ok(bool(si.get("name")), "initialize · hay serverInfo negociado", str(si)[:80])

            # verbo 6 · list_tools
            tools = srv.list_tools()
            self.ok(tools is not None, "list_tools · el server contestó a tools/list")
            tools = tools or []
            nombres = [t.get("name") for t in tools]
            if espera_tools:
                self.ok(len(tools) > 0, "list_tools · la superficie llegó", f"{len(tools)} tools")
            elif not tools:
                self.nota("list_tools · superficie VACÍA — es lo que hay sin el paso humano; "
                          "el verbo está declarado DE_USUARIO en la tabla, no verde")
            else:
                self.nota(f"list_tools · {len(tools)} tools con el consentimiento ya dado")
            self.ok(all(isinstance(n, str) and n for n in nombres),
                    "y todas las publicadas tienen nombre")

            # verbo 8 · invoke — SÓLO LECTURA
            llamadas = [g for g in grab["pasos"] if g["peticion"]["metodo"] == "tools/call"]
            if llamadas:
                self.ok(True, "invoke · hay al menos una llamada grabada",
                        f"{len(llamadas)} grabada(s)")
                arg = llamadas[0]["peticion"]["args"]
                r = srv.call_tool(arg["name"], arg.get("arguments") or {})
                self.ok(r is not None, f"invoke · `{arg['name']}` devolvió respuesta",
                        str(r)[:70].replace("\n", " "))
                # ⚠️ «DEVOLVIÓ RESPUESTA» NO ES «ANDUVO», y confundirlos sería el verde falso
                # que esta serie viene cerrando. Un `[tool error]` grabado es una respuesta
                # perfectamente válida del transporte y una NO-ejecución de la tool.
                #
                # PENDIENTE MEDIDO (S3): en las piezas con credencial, la grabación se queda
                # con la respuesta de la SONDA DE BASURA, no con la real. El verificador
                # llama la misma tool dos veces —una con la llave real y otra con la
                # llave-basura, que es como prueba `credencial=verde`— y el grabador
                # indexa por `(método, args)`: la segunda PISA a la primera. Se ve en `exa`,
                # cuya evidencia en vivo fue un resultado real y cuya grabación quedó con un
                # `401 Invalid API key`. El arreglo es del grabador (versionar las repes), no
                # de acá; hasta entonces esto lo DECLARA en vez de taparlo.
                if "[tool error]" in str(r):
                    self.nota(f"invoke · la respuesta grabada de `{arg['name']}` es un ERROR "
                              f"de la tool, no una ejecución: {str(r)[:90]}")
                    self.nota("PENDIENTE del grabador: con credencial, la sonda de basura "
                              "pisa la llamada real (mismo `(método, args)`)")
                if tool_extra:
                    tool_extra(self, srv, llamadas)
            else:
                self.nota("invoke · NINGUNA llamada grabada — sin consentimiento el ejemplar "
                          "no publica tools que llamar. El verbo NO se cuenta como verde")

            # verbo 9 · persist — el que NO EXISTE en el contrato: se prueba como está
            self.ok(bool(meta.get("huella_receta")),
                    "persist · la grabación reconstruye el veredicto sin el proceso vivo",
                    "el verbo no existe en el contrato; esto mide lo que SÍ hay")
            try:
                srv.stop()
            except Exception:                                          # noqa: BLE001
                pass
        finally:
            if previo is None:
                os.environ.pop("ALEPH_REPLAY", None)
            else:
                os.environ["ALEPH_REPLAY"] = previo

    # ── la calibración roja ─────────────────────────────────────────────────────────
    def calibracion_roja(self):
        from inspection import transporte as TP
        import grabador as G
        print("\n2 · calibración ROJA · el arnés no puede dar verde sin grabación")
        os.environ["ALEPH_REPLAY"] = self.ejemplar + "-que-no-existe"
        cerro = False
        try:
            TP.servidor_stdio()(self.ejemplar, "", [], env=dict(os.environ))
        except G.GrabacionAusente:
            cerro = True
        except Exception:                                              # noqa: BLE001
            pass
        os.environ.pop("ALEPH_REPLAY", None)
        self.ok(cerro, "sin grabación falla CERRADO, no inventa un veredicto")

    # ── el ejemplar es un parámetro ─────────────────────────────────────────────────
    def ejemplar_es_parametro(self, archivo: str, ejemplar_defecto: str):
        print("\n3 · el ejemplar es un parámetro, no la identidad del arnés")
        fuente = Path(archivo).read_text(encoding="utf-8")
        self.ok(f'EJEMPLAR_DEFECTO = "{ejemplar_defecto}"' in fuente,
                "el ejemplar vive en UNA constante, cambiable en una línea")
        self.ok("--ejemplar" in fuente, "y se puede pasar por parámetro")

    # ── el cierre ───────────────────────────────────────────────────────────────────
    def cerrar(self) -> int:
        if self.notas:
            print(f"\n  ({len(self.notas)} cosa(s) declaradas y NO cubiertas — están arriba)")
        print("\n" + (f"══ ✅ ARNÉS «{self.tipo}» VERDE · ejemplar {self.ejemplar} ══"
                      if not self.fallos else
                      f"══ ❌ {len(self.fallos)} FALLO(S): {self.fallos} ══"))
        return 1 if self.fallos else 0


def parser(ejemplar_defecto: str):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--ejemplar", default=ejemplar_defecto,
                    help="qué conector encarna el tipo en esta corrida")
    return ap
