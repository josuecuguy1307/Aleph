#!/usr/bin/env python3
"""
spice_server.py — MCP stdio server del belt de ELECTRONICA: SIMULACION (Bode) + DRC.

Cierra el loop del agente de electrónica: hoy tiene esquemático (KiCad) y precio
(1B-1) pero NO puede SIMULAR. Con esto el agente diseña un filtro → lo simula →
LEE dónde cae el -3dB real → si está fuera de spec ajusta R/C (razonando
f_c = 1/(2πRC)) → re-simula → hasta cumplir. + DRC de N errores a 0.

Tools:
  ac_sweep            — análisis AC REAL con ngspice (headless, CLI, NO el GUI): dado un
                        filtro (RC/RLC + valores), corre el barrido en frecuencia y
                        devuelve la curva de magnitud (dB) y fase, el -3dB MEDIDO y la
                        atenuación en la frecuencia objetivo. Con task_id acumula
                        convergence.json → La Sala lo rinde con el display 1D (la curva
                        deslizándose al target, it.1 FALLA rojo → it.N PASA verde).
  build_filter_schematic — autoría un esquemático KiCad del filtro (vía kicad-sch-api)
                        para poder chequearlo. connect=false deja pines flotantes (errores
                        de DRC), connect=true lo cablea (0 errores).
  run_erc             — corre el ERC/DRC con kicad-cli (headless) sobre un .kicad_sch del
                        workdir y devuelve la lista REAL de infracciones.

Cero fabricación: todo número (magnitud, -3dB, fase, infracciones) sale de ngspice /
kicad-cli en vivo, nunca de memoria. Si la herramienta no está o falla, error honesto.
"""
import json
import math
import os
import subprocess
import shutil
import sys
import tempfile

_NGSPICE = os.environ.get("NGSPICE_BIN", "ngspice")
_KICAD_CLI = os.environ.get(
    "KICAD_CLI_BIN", shutil.which("kicad-cli") or "kicad-cli")
# kicad-sch-api vive en su propio venv (autoría de esquemáticos); se invoca por subprocess.
_KSA_PY = os.environ.get(
    "KICAD_SCH_API_PY", sys.executable)
_TIMEOUT = int(os.environ.get("SPICE_TIMEOUT", "60"))

# [i18n-bi] bilingüe server-side (PUPPET_LANG, default es; no-op hasta que el runtime lo
# setee). Mismo patrón que fem_server.py: lo que RENDERIZA La Sala (descripciones, título/
# métrica de la convergencia, notas, errores honestos) sale en el idioma del usuario.
PUPPET_LANG = "en" if os.environ.get("PUPPET_LANG", "es").lower().startswith("en") else "es"
SPICE_I18N = {
    "es": {
        "tool.ac_sweep.desc": (
            "Corre un análisis AC (barrido en frecuencia) REAL con ngspice sobre un filtro "
            "pasivo y devuelve la respuesta en frecuencia (Bode): magnitud en dB y fase vs "
            "frecuencia, la frecuencia de corte -3dB MEDIDA, y —si pasas target_fc_hz— la "
            "atenuación en esa frecuencia. filter_type: 'rc_lowpass', 'rc_highpass' o "
            "'rlc_bandpass'. Úsala para diseñar/ajustar un filtro: corre el barrido, LEE el "
            "-3dB real, compara con tu objetivo y, si está fuera, cambia R o C (recuerda "
            "f_c = 1/(2·pi·R·C)) y vuelve a correr. Pasa el MISMO task_id en cada iteración del "
            "loop para que La Sala las agrupe como UNA convergencia. Todo número sale del "
            "solver, nunca de memoria."
        ),
        "p.filter_type": "rc_lowpass | rc_highpass | rlc_bandpass (default rc_lowpass).",
        "p.R": "Resistencia R en ohms.",
        "p.C": "Capacitancia C en farads (ej 100e-9 = 100nF).",
        "p.L": "Inductancia L en henrios (solo rlc_bandpass).",
        "p.f_start": "Frecuencia inicial del barrido (default 10).",
        "p.f_stop": "Frecuencia final del barrido (default 1e6).",
        "p.target_fc": "Frecuencia de corte objetivo (spec). Define la atenuación medida en ese punto.",
        "p.task_id": "ID del loop: pasa el mismo en cada iteración → convergencia agrupada en La Sala.",
        "p.iteration_note": "Nota corta de la iteración (qué cambiaste y por qué).",
        "tool.build.desc": (
            "Autoría un esquemático KiCad REAL del filtro (vía kicad-sch-api) en el workspace, "
            "para poder chequearlo con run_erc. connect=true lo cablea completo (sin pines "
            "flotantes → 0 errores de DRC); connect=false deja los pines sin conectar (genera "
            "errores 'pin_not_connected', útil para ver el DRC antes de corregir). Devuelve la "
            "ruta del .kicad_sch."
        ),
        "p.R_ohms": "Resistencia R en ohms.",
        "p.C_farads": "Capacitancia C en farads.",
        "p.filter_type2": "rc_lowpass | rc_highpass (default rc_lowpass).",
        "p.name": "Nombre del esquemático (sin extensión).",
        "p.connect": "true = cableado (0 errores), false = pines flotantes (errores). Default true.",
        "tool.erc.desc": (
            "Corre el chequeo de reglas eléctricas (ERC/DRC) con kicad-cli (headless) sobre un "
            "esquemático .kicad_sch del workspace y devuelve la lista REAL de infracciones "
            "(errores y advertencias). Úsalo para verificar tu diseño: corre el ERC, lee los "
            "errores, corrige (cablea los pines) y vuelve a correr hasta 0 errores."
        ),
        "p.schematic": "Nombre o ruta del .kicad_sch (en el workspace).",
        "err.ngspice_no_output": "ngspice no produjo salida: %s",
        "err.ngspice_parse": "no se pudo parsear la salida de ngspice",
        "err.ngspice_missing": "ngspice no está instalado (brew install ngspice)",
        "err.ngspice_timeout": "ngspice timeout (>%ss)",
        "err.ngspice_failed": "ngspice falló: %s",
        "err.missing_rc": "faltan R_ohms / C_farads",
        "err.ksa_missing": "kicad-sch-api no disponible (%s)",
        "err.build_timeout": "autoría del esquemático timeout",
        "err.build_failed": "no se generó el esquemático: %s",
        "err.missing_schematic": "falta 'schematic'",
        "err.no_schematic": "no existe el esquemático: %s",
        "err.kicad_cli_missing": "kicad-cli no disponible (%s)",
        "err.erc_timeout": "kicad-cli ERC timeout",
        "err.erc_no_report": "kicad-cli no produjo el reporte ERC",
        "note.ac_sweep": "Barrido AC real con ngspice (no de memoria).",
        "note.iteration": " Iteración %d acumulada en la convergencia (La Sala la rinde).",
        "spec.target": "atenuación @ %g Hz ≤ 3 dB (el target queda en la banda de paso)",
        "note.build": "Esquemático KiCad real generado. Corre run_erc para el chequeo.",
        "note.erc": "ERC real con kicad-cli (headless). %d errores, %d advertencias.",
        "conv.title": "Convergencia del filtro — atenuación @ %g Hz",
        "conv.metric": "atenuación @ %g Hz",
    },
    "en": {
        "tool.ac_sweep.desc": (
            "Run a REAL AC analysis (frequency sweep) with ngspice on a passive filter and "
            "return the frequency response (Bode): magnitude in dB and phase vs frequency, the "
            "MEASURED -3dB cutoff frequency, and —if you pass target_fc_hz— the attenuation at "
            "that frequency. filter_type: 'rc_lowpass', 'rc_highpass' or 'rlc_bandpass'. Use it "
            "to design/tune a filter: run the sweep, READ the real -3dB, compare to your target "
            "and, if off-spec, change R or C (remember f_c = 1/(2·pi·R·C)) and run again. Pass "
            "the SAME task_id on each loop iteration so The Room groups them as ONE convergence. "
            "Every number comes from the solver, never from memory."
        ),
        "p.filter_type": "rc_lowpass | rc_highpass | rlc_bandpass (default rc_lowpass).",
        "p.R": "Resistance R in ohms.",
        "p.C": "Capacitance C in farads (e.g. 100e-9 = 100nF).",
        "p.L": "Inductance L in henries (rlc_bandpass only).",
        "p.f_start": "Sweep start frequency (default 10).",
        "p.f_stop": "Sweep stop frequency (default 1e6).",
        "p.target_fc": "Target cutoff frequency (spec). Defines the attenuation measured at that point.",
        "p.task_id": "Loop ID: pass the same one on each iteration → convergence grouped in The Room.",
        "p.iteration_note": "Short iteration note (what you changed and why).",
        "tool.build.desc": (
            "Author a REAL KiCad schematic of the filter (via kicad-sch-api) in the workspace, "
            "so you can check it with run_erc. connect=true wires it fully (no floating pins → "
            "0 DRC errors); connect=false leaves the pins unconnected (generates "
            "'pin_not_connected' errors, useful to see the DRC before fixing). Returns the path "
            "of the .kicad_sch."
        ),
        "p.R_ohms": "Resistance R in ohms.",
        "p.C_farads": "Capacitance C in farads.",
        "p.filter_type2": "rc_lowpass | rc_highpass (default rc_lowpass).",
        "p.name": "Schematic name (no extension).",
        "p.connect": "true = wired (0 errors), false = floating pins (errors). Default true.",
        "tool.erc.desc": (
            "Run the electrical rules check (ERC/DRC) with kicad-cli (headless) over a "
            ".kicad_sch schematic in the workspace and return the REAL list of violations "
            "(errors and warnings). Use it to verify your design: run the ERC, read the errors, "
            "fix them (wire the pins) and run again until 0 errors."
        ),
        "p.schematic": "Name or path of the .kicad_sch (in the workspace).",
        "err.ngspice_no_output": "ngspice produced no output: %s",
        "err.ngspice_parse": "could not parse ngspice output",
        "err.ngspice_missing": "ngspice is not installed (brew install ngspice)",
        "err.ngspice_timeout": "ngspice timeout (>%ss)",
        "err.ngspice_failed": "ngspice failed: %s",
        "err.missing_rc": "missing R_ohms / C_farads",
        "err.ksa_missing": "kicad-sch-api not available (%s)",
        "err.build_timeout": "schematic authoring timeout",
        "err.build_failed": "schematic was not generated: %s",
        "err.missing_schematic": "missing 'schematic'",
        "err.no_schematic": "schematic does not exist: %s",
        "err.kicad_cli_missing": "kicad-cli not available (%s)",
        "err.erc_timeout": "kicad-cli ERC timeout",
        "err.erc_no_report": "kicad-cli produced no ERC report",
        "note.ac_sweep": "Real AC sweep with ngspice (not from memory).",
        "note.iteration": " Iteration %d accumulated into the convergence (The Room renders it).",
        "spec.target": "attenuation @ %g Hz ≤ 3 dB (the target stays in the passband)",
        "note.build": "Real KiCad schematic generated. Run run_erc for the check.",
        "note.erc": "Real ERC with kicad-cli (headless). %d errors, %d warnings.",
        "conv.title": "Filter convergence — attenuation @ %g Hz",
        "conv.metric": "attenuation @ %g Hz",
    },
}


def _t(key):
    return SPICE_I18N.get(PUPPET_LANG, {}).get(key) or SPICE_I18N["es"].get(key) or key


TOOLS = [
    {
        "name": "ac_sweep",
        "description": _t("tool.ac_sweep.desc"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "filter_type": {"type": "string", "description": _t("p.filter_type")},
                "R_ohms": {"type": "number", "description": _t("p.R")},
                "C_farads": {"type": "number", "description": _t("p.C")},
                "L_henries": {"type": "number", "description": _t("p.L")},
                "f_start_hz": {"type": "number", "description": _t("p.f_start")},
                "f_stop_hz": {"type": "number", "description": _t("p.f_stop")},
                "target_fc_hz": {"type": "number", "description": _t("p.target_fc")},
                "task_id": {"type": "string", "description": _t("p.task_id")},
                "iteration_note": {"type": "string", "description": _t("p.iteration_note")},
            },
            "required": ["R_ohms", "C_farads"],
        },
    },
    {
        "name": "build_filter_schematic",
        "description": _t("tool.build.desc"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "R_ohms": {"type": "number", "description": _t("p.R_ohms")},
                "C_farads": {"type": "number", "description": _t("p.C_farads")},
                "filter_type": {"type": "string", "description": _t("p.filter_type2")},
                "name": {"type": "string", "description": _t("p.name")},
                "connect": {"type": "boolean", "description": _t("p.connect")},
            },
            "required": ["R_ohms", "C_farads"],
        },
    },
    {
        "name": "run_erc",
        "description": _t("tool.erc.desc"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematic": {"type": "string", "description": _t("p.schematic")},
            },
            "required": ["schematic"],
        },
    },
]


# ════════════════════════ ngspice — barrido AC ══════════════════════════════

def _netlist(filter_type: str, R: float, C: float, L: float, fstart: float,
             fstop: float, outfile: str, ppd: int = 50) -> str:
    if filter_type == "rc_highpass":
        topo = f"C1 in out {C}\nR1 out 0 {R}"
    elif filter_type == "rlc_bandpass":
        topo = f"L1 in n1 {L}\nC1 n1 out {C}\nR1 out 0 {R}"
    else:  # rc_lowpass (default)
        topo = f"R1 in out {R}\nC1 out 0 {C}"
    return (
        f"* {filter_type} AC sweep (ngspice)\n"
        f"V1 in 0 DC 0 AC 1\n"
        f"{topo}\n"
        f".control\n"
        f"ac dec {ppd} {fstart} {fstop}\n"
        f"wrdata {outfile} vdb(out) vp(out)\n"
        f".endc\n"
        f".end\n"
    )


def _run_ngspice(p: dict):
    """Corre ngspice -b sobre el filtro descrito por `p` y devuelve
    [(freq, mag_db, phase_deg), ...]. Lanza en error."""
    with tempfile.TemporaryDirectory() as td:
        cir = os.path.join(td, "f.cir")
        out = os.path.join(td, "f.txt")
        with open(cir, "w") as f:
            f.write(_netlist(p["filter_type"], p["R"], p["C"], p["L"],
                             p["fstart"], p["fstop"], out, p["ppd"]))
        proc = subprocess.run([_NGSPICE, "-b", cir], capture_output=True, text=True, timeout=_TIMEOUT)
        if not os.path.exists(out):
            raise RuntimeError(_t("err.ngspice_no_output") % (proc.stderr or proc.stdout)[:300])
        pts = []
        for line in open(out):
            c = line.split()
            if len(c) >= 4:
                try:
                    pts.append((float(c[0]), float(c[1]), float(c[3])))
                except ValueError:
                    continue
        if not pts:
            raise RuntimeError(_t("err.ngspice_parse"))
        return pts


def _interp_db_at(pts, f_target):
    """Magnitud (dB) interpolada (en log-f) a la frecuencia objetivo."""
    if f_target <= pts[0][0]:
        return pts[0][1]
    if f_target >= pts[-1][0]:
        return pts[-1][1]
    for i in range(1, len(pts)):
        if pts[i][0] >= f_target:
            f0, d0 = pts[i - 1][0], pts[i - 1][1]
            f1, d1 = pts[i][0], pts[i][1]
            t = (math.log10(f_target) - math.log10(f0)) / (math.log10(f1) - math.log10(f0))
            return d0 + t * (d1 - d0)
    return pts[-1][1]


def _find_3db(pts, filter_type, passband_db):
    """Frecuencia(s) donde la magnitud cruza (passband - 3dB). Devuelve la del corte
    según el tipo: lowpass=corte superior, highpass=corte inferior."""
    thr = passband_db - 3.0
    crossings = []
    for i in range(1, len(pts)):
        d0, d1 = pts[i - 1][1], pts[i][1]
        if (d0 - thr) * (d1 - thr) <= 0 and d0 != d1:
            f0, f1 = pts[i - 1][0], pts[i][0]
            t = (thr - d0) / (d1 - d0)
            fc = 10 ** (math.log10(f0) + t * (math.log10(f1) - math.log10(f0)))
            crossings.append(fc)
    if not crossings:
        return None
    if filter_type == "rc_highpass":
        return crossings[0]      # corte inferior
    return crossings[-1]         # lowpass: corte superior · bandpass: corte alto


def _theoretical_fc(filter_type, R, C, L):
    if filter_type == "rlc_bandpass" and L:
        return 1.0 / (2 * math.pi * math.sqrt(L * C))
    return 1.0 / (2 * math.pi * R * C)


def _attenuation_grid(pts, passband_db, nx_target=64, ny=18):
    """Campo de ATENUACIÓN (dB, = passband - magnitud) para el heatmap de convergencia.
    Tiled verticalmente: columnas = frecuencia (log), color por `limit`=3dB (verde banda de
    paso / rojo banda de rechazo). El borde verde→rojo es el -3dB; al deslizarse el corte
    hacia el target, la banda verde lo cubre."""
    # re-muestrear a nx_target columnas uniformes en índice (ya son log en frecuencia)
    n = len(pts)
    cols = []
    for j in range(nx_target):
        idx = min(n - 1, int(round(j * (n - 1) / (nx_target - 1))))
        att = passband_db - pts[idx][1]
        cols.append(round(max(0.0, att), 3))
    values = cols * ny  # tiled (mismas columnas en cada fila)
    return {"nx": nx_target, "ny": ny, "values": values,
            "min": 0.0, "max": max(6.0, max(cols)), "limit": 3.0, "unit": "dB", "interpolate": True}


def _accumulate_convergence(workdir, task_id, target_fc, att_target, measured_fc, grid, note):
    """Acumula la iteración en convergence.json (mismo patrón que el FEM). El executor la
    surfacea como obra `convergence` → La Sala la rinde con el display 1D."""
    cpath = os.path.join(workdir, "convergence.json")
    conv = None
    if os.path.exists(cpath):
        try:
            conv = json.load(open(cpath))
        except Exception:
            conv = None
    if not (isinstance(conv, dict) and isinstance(conv.get("iterations"), list)
            and conv.get("task_id") == task_id):
        conv = {
            "type": "convergence",
            "title": _t("conv.title") % target_fc,
            "task_id": task_id,
            "metric": {"name": _t("conv.metric") % target_fc, "unit": "dB", "limit": 3.0, "goal": "min"},
            "limit": 3.0,
            "iterations": [],
        }
    n = len(conv["iterations"]) + 1
    conv["iterations"].append({
        "n": n,
        "value": round(att_target, 3),
        "measured_fc_hz": round(measured_fc, 2) if measured_fc else None,
        "grid": grid,
        "note": note or "",
    })
    try:
        with open(cpath, "w", encoding="utf-8") as f:
            json.dump(conv, f, ensure_ascii=False)
    except Exception:
        pass
    return n


def _ac_sweep(args: dict) -> dict:
    filter_type = (args.get("filter_type") or "rc_lowpass").strip()
    R = float(args.get("R_ohms"))
    C = float(args.get("C_farads"))
    L = float(args.get("L_henries") or 0.0)
    fstart = float(args.get("f_start_hz") or 10.0)
    fstop = float(args.get("f_stop_hz") or 1e6)
    target = args.get("target_fc_hz")
    target = float(target) if target else None
    task_id = args.get("task_id")
    note = args.get("iteration_note")

    params = {"filter_type": filter_type, "R": R, "C": C, "L": L,
              "fstart": fstart, "fstop": fstop, "ppd": 50}
    try:
        pts = _run_ngspice(params)
    except FileNotFoundError:
        return {"ok": False, "error": _t("err.ngspice_missing")}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": _t("err.ngspice_timeout") % _TIMEOUT}
    except Exception as exc:
        return {"ok": False, "error": _t("err.ngspice_failed") % exc}

    passband = max(p[1] for p in pts)
    measured_fc = _find_3db(pts, filter_type, passband)
    theoretical_fc = _theoretical_fc(filter_type, R, C, L)

    out = {
        "ok": True,
        "filter_type": filter_type,
        "R_ohms": R, "C_farads": C,
        "theoretical_fc_hz": round(theoretical_fc, 3),
        "measured_f3db_hz": round(measured_fc, 3) if measured_fc else None,
        "passband_db": round(passband, 3),
        "points": len(pts),
        "f_range_hz": [pts[0][0], pts[-1][0]],
        "note": _t("note.ac_sweep"),
    }
    if L:
        out["L_henries"] = L
    # muestra de la curva (para que el cerebro pueda mostrar un chart honesto)
    sample = []
    step = max(1, len(pts) // 14)
    for i in range(0, len(pts), step):
        sample.append({"f_hz": round(pts[i][0], 2), "mag_db": round(pts[i][1], 3), "phase_deg": round(pts[i][2], 2)})
    out["curve_sample"] = sample

    if target is not None:
        db_at = _interp_db_at(pts, target)
        att = passband - db_at
        out["target_fc_hz"] = target
        out["mag_db_at_target"] = round(db_at, 3)
        out["attenuation_at_target_db"] = round(att, 3)
        out["in_spec"] = bool(att <= 3.0)
        out["spec"] = _t("spec.target") % target
        if task_id:
            workdir = os.environ.get("PUPPET_WORKDIR") or os.getcwd()
            grid = _attenuation_grid(pts, passband)
            it_n = _accumulate_convergence(workdir, task_id, target, att, measured_fc, grid, note)
            out["iteration"] = it_n
            out["note"] += _t("note.iteration") % it_n
    return out


# ════════════════════════ KiCad — autoría + ERC ═════════════════════════════

_KSA_GEN = r'''
import sys, json
import kicad_sch_api as ksa
R, C, ftype, path, connect = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5] == "1"
sch = ksa.create_schematic("filter")
r = sch.components.add(lib_id="Device:R", reference="R1", value=R, position=(100, 100))
c = sch.components.add(lib_id="Device:C", reference="C1", value=C, position=(120, 110))
if connect:
    # cablear: nodo de salida R2-C1, y etiquetas de net en los pines extremos → 0 errores
    try:
        sch.add_wire_between_pins("R1", "2", "C1", "1")
    except Exception:
        pass
    def lbl(comp, pin, name):
        p = comp.get_pin_position(pin)
        sch.add_label(name, position=(p.x, p.y))
    if ftype == "rc_highpass":
        lbl(c, "1", "IN"); lbl(r, "2", "OUT"); lbl(r, "1", "OUT"); lbl(c, "2", "IN")
    else:
        lbl(r, "1", "IN"); lbl(r, "2", "OUT"); lbl(c, "1", "OUT"); lbl(c, "2", "GND")
sch.save(path)
print(json.dumps({"ok": True, "path": path}))
'''


def _build_schematic(args: dict) -> dict:
    R = args.get("R_ohms")
    C = args.get("C_farads")
    if R is None or C is None:
        return {"ok": False, "error": _t("err.missing_rc")}
    ftype = (args.get("filter_type") or "rc_lowpass").strip()
    name = (args.get("name") or "filtro").strip().replace("/", "_")
    connect = args.get("connect", True)
    workdir = os.environ.get("PUPPET_WORKDIR") or os.getcwd()
    path = os.path.join(workdir, name + ".kicad_sch")
    Rval = _fmt_eng(R) + "Ω" if isinstance(R, (int, float)) else str(R)
    Cval = _fmt_eng(C, base="F")
    if not os.path.exists(_KSA_PY):
        return {"ok": False, "error": _t("err.ksa_missing") % _KSA_PY}
    try:
        proc = subprocess.run(
            [_KSA_PY, "-c", _KSA_GEN, Rval, Cval, ftype, path, "1" if connect else "0"],
            capture_output=True, text=True, timeout=_TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": _t("err.build_timeout")}
    if not os.path.exists(path):
        return {"ok": False, "error": _t("err.build_failed") % (proc.stderr or proc.stdout)[:300]}
    return {"ok": True, "schematic": os.path.basename(path), "path": path,
            "connected": bool(connect), "R": Rval, "C": Cval, "filter_type": ftype,
            "note": _t("note.build")}


def _fmt_eng(v, base=""):
    v = float(v)
    if base == "F":
        for mult, suf in ((1e-12, "p"), (1e-9, "n"), (1e-6, "u"), (1e-3, "m")):
            if v < mult * 1000:
                return ("%g%s" % (v / mult, suf)) + "F"
        return "%gF" % v
    for mult, suf in ((1e6, "M"), (1e3, "k"), (1, "")):
        if v >= mult:
            return "%g%s" % (v / mult, suf)
    return "%g" % v


def _run_erc(args: dict) -> dict:
    sch = (args.get("schematic") or "").strip()
    if not sch:
        return {"ok": False, "error": _t("err.missing_schematic")}
    workdir = os.environ.get("PUPPET_WORKDIR") or os.getcwd()
    path = sch if os.path.isabs(sch) else os.path.join(workdir, sch)
    if not path.endswith(".kicad_sch"):
        path += ".kicad_sch"
    if not os.path.exists(path):
        return {"ok": False, "error": _t("err.no_schematic") % os.path.basename(path)}
    if not (os.path.isfile(_KICAD_CLI) or shutil.which(_KICAD_CLI)):
        return {"ok": False, "error": _t("err.kicad_cli_missing") % _KICAD_CLI}
    with tempfile.TemporaryDirectory() as td:
        report = os.path.join(td, "erc.json")
        try:
            subprocess.run([_KICAD_CLI, "sch", "erc", "--format", "json", "--severity-all",
                            "-o", report, path], capture_output=True, text=True, timeout=_TIMEOUT)
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": _t("err.erc_timeout")}
        if not os.path.exists(report):
            return {"ok": False, "error": _t("err.erc_no_report")}
        rep = json.load(open(report))
    viols = [v for s in rep.get("sheets", []) for v in s.get("violations", [])]
    errors = [v for v in viols if v.get("severity") == "error"]
    warnings = [v for v in viols if v.get("severity") == "warning"]
    return {
        "ok": True,
        "schematic": os.path.basename(path),
        "error_count": len(errors),
        "warning_count": len(warnings),
        "violations": [{"severity": v.get("severity"), "type": v.get("type"),
                        "description": (v.get("description") or "")[:120]} for v in viols[:20]],
        "clean": len(errors) == 0,
        "note": _t("note.erc") % (len(errors), len(warnings)),
    }


# ════════════════════════ MCP stdio (idéntico a fem/precio) ══════════════════

def _send(obj: dict):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _handle(req: dict):
    method = req.get("method", "")
    req_id = req.get("id")
    params = req.get("params", {})
    if method == "initialize":
        _send({"jsonrpc": "2.0", "id": req_id, "result": {
            "protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
            "serverInfo": {"name": "spice-server", "version": "0.1.0"}}})
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        _send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {}) or {}
        try:
            if name == "ac_sweep":
                val = _ac_sweep(args)
            elif name == "build_filter_schematic":
                val = _build_schematic(args)
            elif name == "run_erc":
                val = _run_erc(args)
            else:
                raise ValueError("unknown tool %s" % name)
            is_err = not val.get("ok", True)
            _send({"jsonrpc": "2.0", "id": req_id, "result": {
                "content": [{"type": "text", "text": json.dumps(val, ensure_ascii=False)}],
                "isError": is_err}})
        except Exception as exc:
            _send({"jsonrpc": "2.0", "id": req_id, "result": {
                "content": [{"type": "text", "text": "error: %s" % exc}], "isError": True}})
    else:
        if req_id is not None:
            _send({"jsonrpc": "2.0", "id": req_id,
                   "error": {"code": -32601, "message": "Method not found: %s" % method}})


def main():
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            req = json.loads(raw)
        except json.JSONDecodeError:
            continue
        _handle(req)


if __name__ == "__main__":
    main()
