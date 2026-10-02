#!/usr/bin/env python3
"""maad_server.py — MCP stdio server: BIOACÚSTICA con scikit-maad (datos REALES).

Tool `analyze_recording`: dado un WAV, carga la señal, computa un espectrograma y el
Acoustic Complexity Index (ACI, Pieretti 2011) + el centroide espectral, TODO con
scikit-maad/numpy sobre la señal real — nunca de memoria. Además escribe el espectrograma
como obra `fieldplot` (heatmap frecuencia×tiempo) en ${PUPPET_WORKDIR} → el executor la
surfacea y La Sala la rinde.

Tool `acoustic_complexity_index`: computa el ACI sobre una matriz de espectrograma cruda
(2D). Primitiva exacta y verificable — sobre [[1,3,1],[2,2,2]] da 0.8 EXACTO (bin0: d=4,s=5
→0.8; bin1: d=0→0). Un motor alucinado no cae en 0.8; el maad real sí.

Patrón gemelo de product/belts/finanzas/backtest_server.py y fem_server.py: JSON-RPC por
stdin/stdout, cómputo pesado con import LAZY. Spawned vía `uv run --with scikit-maad --with
numpy` (el belt declara el command) → corre aislado, sin tocar el venv del backend. maad se
importa DENTRO de la tool para que el server responda initialize/tools/list al toque.

Honestidad de fallos (para la atribución de capas, H12/H15a): todo error devuelve
{"ok": false, "error": "..."} + isError=true. Un archivo que no existe / un WAV corrupto es
un fallo REPORTADO honesto, no un número inventado. Simplificaciones: espectrograma con los
parámetros default de maad (nperseg/noverlap de sound.spectrogram); ACI sumado sobre bins.
"""
import os
import sys
import json
import math


def _finite(x):
    """NaN/inf → None (JSON válido + honesto: un valor indefinido no se inventa)."""
    try:
        xf = float(x)
        return xf if math.isfinite(xf) else None
    except Exception:
        return None


TOOLS = [
    {
        "name": "analyze_recording",
        "description": (
            "Analiza una grabación bioacústica REAL (WAV) con scikit-maad: computa un "
            "espectrograma, el Acoustic Complexity Index (ACI) y el centroide espectral, y "
            "renderiza el espectrograma como heatmap. Todo número sale del análisis de la "
            "señal, JAMÁS de memoria. Pasa la ruta del WAV. Si el archivo no existe o no se "
            "puede leer, se reporta el fallo honesto (no se inventa un resultado)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "wav_path": {
                    "type": "string",
                    "description": "Ruta al archivo WAV (absoluta, o relativa a ${PUPPET_WORKDIR}).",
                },
            },
            "required": ["wav_path"],
        },
    },
    {
        "name": "acoustic_complexity_index",
        "description": (
            "Computa el Acoustic Complexity Index (ACI, Pieretti 2011) sobre una matriz de "
            "espectrograma cruda (lista 2D de potencias, filas=frecuencia, columnas=tiempo). "
            "El número sale del cálculo real de scikit-maad. Ej.: [[1,3,1],[2,2,2]] → 0.8."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "spectrogram": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "number"}},
                    "description": "Matriz 2D del espectrograma (filas=frecuencia, columnas=tiempo).",
                },
            },
            "required": ["spectrogram"],
        },
    },
]


def _resolve_wav(wav_path: str) -> str:
    if os.path.isabs(wav_path):
        return wav_path
    wd = os.environ.get("PUPPET_WORKDIR") or os.getcwd()
    return os.path.join(wd, wav_path)


def _run_analyze(args: dict) -> dict:
    wav_path = (args.get("wav_path") or "").strip()
    if not wav_path:
        return {"ok": False, "error": "wav_path es requerido"}
    path = _resolve_wav(wav_path)
    if not os.path.exists(path):
        return {"ok": False, "error": "archivo no encontrado: %s" % wav_path}
    try:
        import numpy as np
        from maad import sound, features
    except Exception as e:  # pragma: no cover
        return {"ok": False, "error": "scikit-maad/numpy no disponible: %s" % e}

    try:
        s, fs = sound.load(path)
        Sxx, tn, fn, ext = sound.spectrogram(s, fs)
    except Exception as e:
        return {"ok": False, "error": "no pude leer/analizar el WAV: %s" % e}

    try:
        _, _, aci_sum = features.acoustic_complexity_index(Sxx)
        aci = _finite(aci_sum)                       # tono puro → ACI indefinido → null honesto
        # centroide espectral = media ponderada de la frecuencia por la potencia media por bin
        P = Sxx.mean(axis=1)
        centroid = _finite((fn * P).sum() / P.sum()) if float(P.sum()) > 0 else None
        duration = float(len(s)) / float(fs)
    except Exception as e:
        return {"ok": False, "error": "fallo el cálculo de índices: %s" % e}

    # ── espectrograma → obra `fieldplot` (heatmap freq×tiempo) en el workdir ──
    # Los índices (ACI, centroide) ya se computaron sobre la señal COMPLETA arriba. Acá sólo
    # el heatmap VISUAL se downsamplea a una grilla gruesa (~64×128) — un espectrograma full
    # (p.ej. 512×1682 = 861k celdas → 7.9 MB) es impracticable para La Sala y rompe la captura.
    try:
        Sdb = 10.0 * np.log10(Sxx + 1e-12)          # dB, resolución completa
        fy, fx = Sdb.shape
        NY, NX = min(64, fy), min(128, fx)          # grilla visual gruesa
        yi = np.linspace(0, fy, NY + 1).astype(int)
        xi = np.linspace(0, fx, NX + 1).astype(int)
        coarse = np.empty((NY, NX), dtype=float)
        for a in range(NY):
            for b in range(NX):
                blk = Sdb[yi[a]:max(yi[a] + 1, yi[a + 1]), xi[b]:max(xi[b] + 1, xi[b + 1])]
                coarse[a, b] = float(blk.mean()) if blk.size else float(Sdb[min(yi[a], fy - 1), min(xi[b], fx - 1)])
        vals = [round(float(v), 3) for v in coarse[::-1].flatten()]  # freq alta arriba (y=0 arriba)
        fieldplot = {
            "type": "fieldplot",
            "title": "Espectrograma (scikit-maad)",
            "source": "scikit-maad (real)",
            "slice": "frecuencia (Hz, eje Y) × tiempo (s, eje X) — heatmap %dx%d de un espectrograma %dx%d" % (NY, NX, fy, fx),
            "grid": {
                "nx": int(NX), "ny": int(NY), "values": vals,
                "min": round(float(coarse.min()), 3), "max": round(float(coarse.max()), 3),
                "unit": "dB", "interpolate": True,
            },
        }
        wd = os.environ.get("PUPPET_WORKDIR") or os.getcwd()
        with open(os.path.join(wd, "spectrogram.fieldplot.json"), "w") as f:
            json.dump(fieldplot, f, ensure_ascii=False)
        rendered = True
    except Exception:
        rendered = False

    return {
        "ok": True,
        "aci": round(aci, 4) if aci is not None else None,
        "spectral_centroid_hz": round(centroid, 2) if centroid is not None else None,
        "duration_s": round(duration, 4),
        "fs_hz": int(fs),
        "n_freq_bins": int(Sxx.shape[0]),
        "n_time_bins": int(Sxx.shape[1]),
        "spectrogram_rendered": rendered,
        "note": ("ACI (Pieretti 2011) sumado sobre bins de frecuencia + centroide espectral, "
                 "reales de scikit-maad sobre la señal. Espectrograma con parámetros default de "
                 "maad.sound.spectrogram."),
    }


def _run_aci_matrix(args: dict) -> dict:
    spec = args.get("spectrogram")
    if not isinstance(spec, list) or not spec or not all(isinstance(r, list) and r for r in spec):
        return {"ok": False, "error": "spectrogram debe ser una matriz 2D no vacía"}
    try:
        import numpy as np
        from maad import features
    except Exception as e:  # pragma: no cover
        return {"ok": False, "error": "scikit-maad/numpy no disponible: %s" % e}
    try:
        Sxx = np.array(spec, dtype=float)
        if Sxx.ndim != 2:
            return {"ok": False, "error": "spectrogram debe ser 2D (filas=freq, cols=tiempo)"}
        _, _, aci_sum = features.acoustic_complexity_index(Sxx)
    except Exception as e:
        return {"ok": False, "error": "fallo el cálculo de ACI: %s" % e}
    return {
        "ok": True,
        "aci": round(float(aci_sum), 6),
        "shape": [int(Sxx.shape[0]), int(Sxx.shape[1])],
        "note": "ACI (Pieretti 2011) sumado sobre bins de frecuencia, real de scikit-maad.",
    }


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
            "serverInfo": {"name": "maad-server", "version": "0.1.0"}}})
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        _send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {}) or {}
        try:
            if name == "analyze_recording":
                val = _run_analyze(args)
            elif name == "acoustic_complexity_index":
                val = _run_aci_matrix(args)
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
