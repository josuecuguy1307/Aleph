#!/usr/bin/env python3
"""
segmentacion_server.py — MCP stdio server del belt de MEDICINA: VISOR + SEGMENTACIÓN.

READ-ONLY · DEV/TEST · NO diagnostica. Opera SOBRE el volumen CT (sintético/de-prueba
público de 3D Slicer, anonimizado) que vive en Orthanc. Le da al agente lo que el belt
de metadata no podía: MANIPULAR la imagen médica —algo que un chat no puede hacer—:

  windowing(preset)        — aplica una ventana radiológica (pulmón/hueso/mediastino):
                             ajusta window/level y devuelve la imagen 2D resultante.
  extract_slice(plane)     — extrae un corte en cualquiera de los 3 planos
                             (axial/coronal/sagittal) reslicing el volumen (pydicom/numpy).
  segment_structure(...)   — segmenta una estructura (pulmón o hueso) por umbral de
                             Hounsfield + componentes conexas + morfología → MÁSCARA real,
                             con su recuento de voxels y volumen. La pinta como overlay 2D.

INVARIANTES de seguridad:
  · Solo LECTURA del PACS (GET a Orthanc). Nunca escribe, mueve ni borra (no C-STORE).
  · NO diagnostica ni da conducta clínica: reporta mediciones geométricas, nada más.
  · Todo número (HU, dimensiones, voxels, área) sale del volumen REAL, jamás inventado.
  · El volumen es de DEV/TEST anonimizado; el legal-gate de medicina bloquea prod (HIPAA).

Imágenes: se escriben como PNG en ${PUPPET_WORKDIR} (descargables) y la máscara además
como `segmentation.imagen.json` (type=imagen) → La Sala la rinde con el renderer `imagen`.
"""
import base64
import io
import json
import os
import sys

import numpy as np
import pydicom
import requests
from PIL import Image
from scipy import ndimage

_ORTHANC = os.environ.get("ORTHANC_URL", "http://localhost:8042")
_TIMEOUT = int(os.environ.get("MEDSEG_TIMEOUT", "60"))
_SERIES_UID = os.environ.get("MEDSEG_SERIES_UID")  # opcional: fija una serie concreta

# [i18n-bi] bilingüe server-side (PUPPET_LANG, default es; no-op hasta que el runtime lo
# setee). Mismo patrón que fem_server.py: lo que RENDERIZA La Sala (labels de tejido,
# descripciones, títulos/alt de las imágenes, notas, errores) sale en el idioma del usuario.
PUPPET_LANG = "en" if os.environ.get("PUPPET_LANG", "es").lower().startswith("en") else "es"
SEG_I18N = {
    "es": {
        "label.lung": "pulmón", "label.bone": "hueso", "label.mediastinum": "mediastino",
        "tool.windowing.desc": (
            "Aplica una ventana radiológica (preset) al CT y devuelve la imagen 2D resultante. "
            "preset: 'lung' (pulmón, WL -600/WW 1500), 'bone' (hueso, WL 300/WW 1500) o "
            "'mediastinum' (mediastino, WL 40/WW 400). Distintos presets resaltan distintos "
            "tejidos (la misma imagen se ve MUY diferente). Opcional: plane (axial/coronal/"
            "sagittal) e index del corte. Solo lectura; todo sale del volumen real."
        ),
        "tool.extract.desc": (
            "Extrae un corte del volumen CT en el plano pedido (axial, coronal o sagittal), "
            "reslicing el volumen 3D. Devuelve las dimensiones del corte (px y mm) y la imagen. "
            "Úsalo para recorrer la anatomía en los 3 planos. Solo lectura."
        ),
        "tool.segment.desc": (
            "Segmenta una estructura anatómica en el CT por umbral de Hounsfield + componentes "
            "conexas + morfología, y devuelve la MÁSCARA con su recuento de voxels y volumen en "
            "mL. structure: 'lung' (pulmón) o 'bone' (hueso). Pinta la máscara como overlay 2D "
            "sobre el corte (artifact imagen para La Sala). Es una segmentación REAL sobre el "
            "volumen, NO un overlay falso. No diagnostica: solo mide. Solo lectura."
        ),
        "tool.volume.desc": (
            "Genera el VOLUMEN 3D rotable de una estructura: corre marching cubes sobre la "
            "máscara segmentada (la misma de segment_structure) y produce un mesh 3D que La Sala "
            "renderiza rotable con el mouse (Three.js). structure: 'lung' (pulmón) o 'bone' "
            "(hueso). El mesh sale del volumen CT real de Orthanc, no es un modelo prefab. Es el "
            "'scan gris → anatomía 3D'. detail: low|medium|high (densidad del mesh). READ-ONLY, "
            "no diagnostica."
        ),
        "p.preset": "lung | bone | mediastinum",
        "p.plane": "axial | coronal | sagittal (default axial)",
        "p.index": "Índice del corte (default: el del medio).",
        "p.plane2": "axial | coronal | sagittal",
        "p.preset2": "Ventana a aplicar (default mediastinum).",
        "p.structure": "lung | bone",
        "p.plane_overlay": "Plano del overlay (default axial).",
        "p.index_overlay": "Índice del corte del overlay (default: el del medio).",
        "p.detail": "low | medium | high (default medium).",
        "err.no_series": "no se encontró una serie CT en Orthanc (%s)",
        "err.preset_invalid": "preset inválido (%s); usa lung|bone|mediastinum",
        "err.plane_invalid": "plane inválido (%s); usa axial|coronal|sagittal",
        "err.structure_invalid": "structure inválida (%s); usa lung|bone",
        "err.skimage": "scikit-image no disponible (pip install scikit-image en el venv medseg)",
        "err.mask_empty": "máscara vacía/insuficiente para mesh (%d voxels)",
        "note.windowing": ("Ventana %s (WL %d/WW %d) aplicada al CT real. Distintos presets cambian "
                           "qué tejido se ve (mira windowed_mean/saturados)."),
        "note.extract": "Corte %s #%d del volumen CT real (reslice 3D).",
        "title.volume": "Volumen 3D — %s (%d triángulos)",
        "source.volume": "marching cubes sobre la máscara real del CT (Orthanc)",
        "rendered.volume": "volume3d (mesh rotable) en La Sala",
        "note.volume": ("Mesh 3D por marching cubes sobre la máscara REAL de %s (umbral HU [%d,%d]) del "
                        "volumen CT de Orthanc. %d triángulos. READ-ONLY, no diagnostica."),
        "disclaimer": "Herramienta de DEV/TEST. No es diagnóstico médico.",
        "alt.segment": "Segmentación de %s sobre CT (overlay)",
        "title.segment": "Segmentación: %s (%.0f mL)",
        "rendered.segment": "imagen (overlay) en La Sala",
        "note.segment": ("Segmentación REAL de %s por umbral HU [%d,%d] + componentes conexas + "
                         "morfología sobre el volumen CT. Mide, NO diagnostica."),
    },
    "en": {
        "label.lung": "lung", "label.bone": "bone", "label.mediastinum": "mediastinum",
        "tool.windowing.desc": (
            "Apply a radiological window (preset) to the CT and return the resulting 2D image. "
            "preset: 'lung' (WL -600/WW 1500), 'bone' (WL 300/WW 1500) or 'mediastinum' "
            "(WL 40/WW 400). Different presets highlight different tissues (the same image looks "
            "VERY different). Optional: plane (axial/coronal/sagittal) and slice index. "
            "Read-only; everything comes from the real volume."
        ),
        "tool.extract.desc": (
            "Extract a slice of the CT volume in the requested plane (axial, coronal or "
            "sagittal), reslicing the 3D volume. Returns the slice dimensions (px and mm) and the "
            "image. Use it to walk the anatomy across the 3 planes. Read-only."
        ),
        "tool.segment.desc": (
            "Segment an anatomical structure in the CT by Hounsfield threshold + connected "
            "components + morphology, and return the MASK with its voxel count and volume in mL. "
            "structure: 'lung' or 'bone'. Paints the mask as a 2D overlay on the slice (image "
            "artifact for The Room). It is a REAL segmentation over the volume, NOT a fake "
            "overlay. It does not diagnose: it only measures. Read-only."
        ),
        "tool.volume.desc": (
            "Generate the rotatable 3D VOLUME of a structure: runs marching cubes over the "
            "segmented mask (the same as segment_structure) and produces a 3D mesh that The Room "
            "renders rotatable with the mouse (Three.js). structure: 'lung' or 'bone'. The mesh "
            "comes from the real Orthanc CT volume, it is not a prefab model. It is the "
            "'gray scan → 3D anatomy'. detail: low|medium|high (mesh density). READ-ONLY, "
            "does not diagnose."
        ),
        "p.preset": "lung | bone | mediastinum",
        "p.plane": "axial | coronal | sagittal (default axial)",
        "p.index": "Slice index (default: the middle one).",
        "p.plane2": "axial | coronal | sagittal",
        "p.preset2": "Window to apply (default mediastinum).",
        "p.structure": "lung | bone",
        "p.plane_overlay": "Overlay plane (default axial).",
        "p.index_overlay": "Overlay slice index (default: the middle one).",
        "p.detail": "low | medium | high (default medium).",
        "err.no_series": "no CT series found in Orthanc (%s)",
        "err.preset_invalid": "invalid preset (%s); use lung|bone|mediastinum",
        "err.plane_invalid": "invalid plane (%s); use axial|coronal|sagittal",
        "err.structure_invalid": "invalid structure (%s); use lung|bone",
        "err.skimage": "scikit-image not available (pip install scikit-image in the medseg venv)",
        "err.mask_empty": "empty/insufficient mask for a mesh (%d voxels)",
        "note.windowing": ("%s window (WL %d/WW %d) applied to the real CT. Different presets change "
                           "which tissue is visible (see windowed_mean/saturated)."),
        "note.extract": "%s slice #%d of the real CT volume (3D reslice).",
        "title.volume": "3D volume — %s (%d triangles)",
        "source.volume": "marching cubes over the real CT mask (Orthanc)",
        "rendered.volume": "volume3d (rotatable mesh) in The Room",
        "note.volume": ("3D mesh by marching cubes over the REAL %s mask (HU threshold [%d,%d]) from "
                        "the Orthanc CT volume. %d triangles. READ-ONLY, does not diagnose."),
        "disclaimer": "DEV/TEST tool. Not a medical diagnosis.",
        "alt.segment": "Segmentation of %s over CT (overlay)",
        "title.segment": "Segmentation: %s (%.0f mL)",
        "rendered.segment": "image (overlay) in The Room",
        "note.segment": ("REAL segmentation of %s by HU threshold [%d,%d] + connected components + "
                         "morphology over the CT volume. Measures, does NOT diagnose."),
    },
}


def _t(key):
    return SEG_I18N.get(PUPPET_LANG, {}).get(key) or SEG_I18N["es"].get(key) or key


# Ventanas radiológicas estándar (Window Level / Window Width, en HU).
PRESETS = {
    "lung":        {"wl": -600, "ww": 1500, "label": _t("label.lung")},
    "bone":        {"wl":  300, "ww": 1500, "label": _t("label.bone")},
    "mediastinum": {"wl":   40, "ww":  400, "label": _t("label.mediastinum")},
}
# Umbrales de Hounsfield por estructura.
STRUCTURES = {
    "lung": {"lo": -1000, "hi": -400, "label": _t("label.lung"), "color": (80, 200, 255)},
    "bone": {"lo":  200,  "hi": 3500, "label": _t("label.bone"),  "color": (255, 210, 90)},
}

TOOLS = [
    {
        "name": "windowing",
        "description": _t("tool.windowing.desc"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "preset": {"type": "string", "description": _t("p.preset")},
                "plane": {"type": "string", "description": _t("p.plane")},
                "index": {"type": "integer", "description": _t("p.index")},
            },
            "required": ["preset"],
        },
    },
    {
        "name": "extract_slice",
        "description": _t("tool.extract.desc"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "plane": {"type": "string", "description": _t("p.plane2")},
                "index": {"type": "integer", "description": _t("p.index")},
                "preset": {"type": "string", "description": _t("p.preset2")},
            },
            "required": ["plane"],
        },
    },
    {
        "name": "segment_structure",
        "description": _t("tool.segment.desc"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "structure": {"type": "string", "description": _t("p.structure")},
                "plane": {"type": "string", "description": _t("p.plane_overlay")},
                "index": {"type": "integer", "description": _t("p.index_overlay")},
            },
            "required": ["structure"],
        },
    },
    {
        "name": "render_volume_3d",
        "description": _t("tool.volume.desc"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "structure": {"type": "string", "description": _t("p.structure")},
                "detail": {"type": "string", "description": _t("p.detail")},
            },
            "required": ["structure"],
        },
    },
]

# ── carga del volumen desde Orthanc (cache por proceso) ──────────────────────
_VOL = None  # dict: {hu (z,y,x), sx, sy, sz, series_id, patient, study}


def _find_series_id():
    if _SERIES_UID:
        for sid in requests.get(f"{_ORTHANC}/series", timeout=_TIMEOUT).json():
            s = requests.get(f"{_ORTHANC}/series/{sid}", timeout=_TIMEOUT).json()
            if s.get("MainDicomTags", {}).get("SeriesInstanceUID") == _SERIES_UID:
                return sid
    # si no, la serie CT con MÁS instancias (= el volumen, no el corte único)
    best, best_n = None, 0
    for sid in requests.get(f"{_ORTHANC}/series", timeout=_TIMEOUT).json():
        s = requests.get(f"{_ORTHANC}/series/{sid}", timeout=_TIMEOUT).json()
        if s.get("MainDicomTags", {}).get("Modality") == "CT" and len(s.get("Instances", [])) > best_n:
            best, best_n = sid, len(s["Instances"])
    return best


def _load_volume():
    global _VOL
    if _VOL is not None:
        return _VOL
    sid = _find_series_id()
    if not sid:
        raise RuntimeError(_t("err.no_series") % _ORTHANC)
    s = requests.get(f"{_ORTHANC}/series/{sid}", timeout=_TIMEOUT).json()
    slices = []
    meta = {}
    for iid in s["Instances"]:
        raw = requests.get(f"{_ORTHANC}/instances/{iid}/file", timeout=_TIMEOUT).content
        ds = pydicom.dcmread(io.BytesIO(raw))
        z = float(ds.ImagePositionPatient[2])
        hu = ds.pixel_array.astype(np.float32) * float(ds.RescaleSlope) + float(ds.RescaleIntercept)
        slices.append((z, hu))
        if not meta:
            sy, sx = [float(v) for v in ds.PixelSpacing]
            meta = {"sx": sx, "sy": sy, "patient": str(ds.PatientName),
                    "study": str(getattr(ds, "StudyDescription", "")), "modality": ds.Modality}
    slices.sort(key=lambda t: t[0])
    vol = np.stack([h for _, h in slices]).astype(np.int16)  # z,y,x
    sz = abs(slices[1][0] - slices[0][0]) if len(slices) > 1 else 1.0
    _VOL = {"hu": vol, "sx": meta["sx"], "sy": meta["sy"], "sz": sz,
            "series_id": sid, "patient": meta["patient"], "study": meta["study"],
            "modality": meta["modality"]}
    return _VOL


# ── helpers de imagen ────────────────────────────────────────────────────────

def _window(a, wl, ww):
    lo = wl - ww / 2.0
    return np.clip((a - lo) / ww * 255.0, 0, 255).astype(np.uint8)


def _reslice(vol, plane, index):
    """Devuelve (img2d_HU, sp_col_mm, sp_row_mm, n, used_index). Reslice físico."""
    Z, Y, X = vol["hu"].shape
    sx, sy, sz = vol["sx"], vol["sy"], vol["sz"]
    if plane == "coronal":
        n = Y; idx = Y // 2 if index is None else max(0, min(Y - 1, index))
        img = np.flipud(vol["hu"][:, idx, :]); return img, sx, sz, n, idx
    if plane == "sagittal":
        n = X; idx = X // 2 if index is None else max(0, min(X - 1, index))
        img = np.flipud(vol["hu"][:, :, idx]); return img, sy, sz, n, idx
    n = Z; idx = Z // 2 if index is None else max(0, min(Z - 1, index))  # axial
    return vol["hu"][idx], sx, sy, n, idx


def _to_physical(gray, sp_col, sp_row, max_side=512):
    """Reescala a aspecto físico (corrige spacing anisótropo de coronal/sagittal)."""
    im = Image.fromarray(gray)
    w, h = im.size
    pw, ph = w * sp_col, h * sp_row
    scale = max_side / max(pw, ph)
    return im.resize((max(1, int(pw * scale)), max(1, int(ph * scale))), Image.BILINEAR)


def _png_b64(im):
    buf = io.BytesIO(); im.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _write_png(im, name):
    workdir = os.environ.get("PUPPET_WORKDIR") or os.getcwd()
    path = os.path.join(workdir, name)
    try:
        im.save(path); return os.path.basename(path)
    except Exception:
        return None


def _clear_border_3d(mask):
    lab, _ = ndimage.label(mask)
    border = set()
    for sl in (lab[0], lab[-1], lab[:, 0], lab[:, -1], lab[:, :, 0], lab[:, :, -1]):
        border.update(np.unique(sl).tolist())
    border.discard(0)
    if not border:
        return mask
    return mask & ~np.isin(lab, list(border))


# ── tools ────────────────────────────────────────────────────────────────────

def _windowing(args):
    preset = (args.get("preset") or "").strip()
    if preset not in PRESETS:
        return {"ok": False, "error": _t("err.preset_invalid") % preset}
    vol = _load_volume()
    plane = (args.get("plane") or "axial").strip()
    img_hu, sp_c, sp_r, n, idx = _reslice(vol, plane, args.get("index"))
    p = PRESETS[preset]
    gray = _window(img_hu, p["wl"], p["ww"])
    im = _to_physical(gray, sp_c, sp_r) if plane != "axial" else Image.fromarray(gray)
    fname = _write_png(im.convert("L"), f"windowing_{preset}_{plane}.png")
    return {
        "ok": True, "preset": preset, "preset_label": p["label"],
        "window_level": p["wl"], "window_width": p["ww"], "plane": plane, "index": idx, "slices": n,
        "output_px": list(im.size),
        "windowed_mean": round(float(gray.mean()), 2),
        "windowed_std": round(float(gray.std()), 2),
        "saturated_white_pct": round(float((gray == 255).mean() * 100), 2),
        "saturated_black_pct": round(float((gray == 0).mean() * 100), 2),
        "image_file": fname,
        "note": _t("note.windowing") % (p["label"], p["wl"], p["ww"]),
        "read_only": True,
    }


def _extract_slice(args):
    plane = (args.get("plane") or "").strip()
    if plane not in ("axial", "coronal", "sagittal"):
        return {"ok": False, "error": _t("err.plane_invalid") % plane}
    vol = _load_volume()
    preset = args.get("preset") if args.get("preset") in PRESETS else "mediastinum"
    img_hu, sp_c, sp_r, n, idx = _reslice(vol, plane, args.get("index"))
    p = PRESETS[preset]
    im = _to_physical(_window(img_hu, p["wl"], p["ww"]), sp_c, sp_r) if plane != "axial" \
        else Image.fromarray(_window(img_hu, p["wl"], p["ww"]))
    fname = _write_png(im.convert("L"), f"slice_{plane}_{idx}.png")
    return {
        "ok": True, "plane": plane, "index": idx, "slices_in_plane": n,
        "voxel_dims": list(img_hu.shape[::-1]),
        "mm_extent": [round(img_hu.shape[1] * sp_c, 1), round(img_hu.shape[0] * sp_r, 1)],
        "output_px": list(im.size), "preset": preset,
        "hu_min": int(img_hu.min()), "hu_max": int(img_hu.max()),
        "image_file": fname,
        "note": _t("note.extract") % (plane, idx),
        "read_only": True,
    }


def _compute_mask(hu, structure):
    """Máscara 3D booleana de la estructura (umbral HU + componentes conexas + morfología).
    Compartida por segment_structure (overlay 2D) y render_volume_3d (mesh 3D)."""
    st = STRUCTURES[structure]
    raw = (hu >= st["lo"]) & (hu <= st["hi"])
    if structure == "lung":
        # Pulmón = aire DENTRO del torso. (Border-clear no sirve: los pulmones se conectan
        # al aire exterior por la tráquea.) 1) máscara del cuerpo (mayor componente de tejido,
        # con los pulmones rellenados como huecos por corte); 2) aire dentro del cuerpo;
        # 3) los 2 componentes mayores (pulmón izq/der); 4) rellenar vasos.
        tissue = hu > -300
        lab_t, nt = ndimage.label(tissue)
        body = (lab_t == (int(np.argmax(ndimage.sum(np.ones_like(lab_t, dtype=np.int64), lab_t,
                range(1, nt + 1)))) + 1)) if nt else tissue
        body_filled = np.empty_like(body)
        for z in range(body.shape[0]):
            body_filled[z] = ndimage.binary_fill_holes(body[z])
        lung_air = raw & body_filled
        lab, nlab = ndimage.label(lung_air)
        if nlab:
            sizes = ndimage.sum(np.ones_like(lab, dtype=np.int64), lab, range(1, nlab + 1))
            order = np.argsort(sizes)[::-1]
            keep = [int(order[k]) + 1 for k in range(min(2, len(order))) if sizes[order[k]] > 20000]
            mask = np.isin(lab, keep) if keep else lung_air
        else:
            mask = lung_air
        for z in range(mask.shape[0]):
            mask[z] = ndimage.binary_fill_holes(mask[z])
    else:  # bone
        mask = ndimage.binary_fill_holes(raw)
        lab, nlab = ndimage.label(mask)
        if nlab:
            sizes = ndimage.sum(np.ones_like(lab, dtype=np.int64), lab, range(1, nlab + 1))
            big = [i + 1 for i, s in enumerate(sizes) if s > 200]   # quitar ruido aislado
            mask = np.isin(lab, big) if big else mask
    return mask


# ── DETALLE → step_size de marching cubes (más step = menos triángulos) ──────
_DETAIL_STEP = {"low": 3, "medium": 2, "high": 1}


def _render_volume_3d(args):
    """Genera el MESH 3D de la estructura (marching cubes sobre la máscara real) y lo emite
    como artifact `volume3d` → La Sala lo rinde rotable (Three.js). El mesh sale del volumen
    de Orthanc, no es un modelo prefab. READ-ONLY, no diagnostica."""
    structure = (args.get("structure") or "").strip()
    if structure not in STRUCTURES:
        return {"ok": False, "error": _t("err.structure_invalid") % structure}
    try:
        from skimage import measure
    except Exception:
        return {"ok": False, "error": _t("err.skimage")}
    vol = _load_volume()
    st = STRUCTURES[structure]
    mask = _compute_mask(vol["hu"], structure)
    voxels = int(mask.sum())
    if voxels < 1000:
        return {"ok": False, "error": _t("err.mask_empty") % voxels}

    detail = (args.get("detail") or "medium").strip()
    step = _DETAIL_STEP.get(detail, 2)
    ds = 2  # downsample isótropo: malla más liviana, rotación fluida en M3
    sub_b = mask[::ds, ::ds, ::ds]
    # cierre morfológico: puentea los huecos sub-voxel de los huesos finos (costillas) tras el
    # downsample → caja torácica conectada en vez de fragmentos. NO fabrica: une lo que ya está.
    sub_b = ndimage.binary_closing(sub_b, iterations=2)
    sub = ndimage.gaussian_filter(sub_b.astype(np.float32), 0.8)  # superficie más suave
    sp = (vol["sz"] * ds, vol["sy"] * ds, vol["sx"] * ds)  # spacing (z,y,x) en mm
    verts, faces, _normals, _ = measure.marching_cubes(sub, level=0.5, spacing=sp, step_size=step)
    # verts vienen en (z,y,x) mm. Para Three.js → (x, -z, -y): x lateral, -z arriba (cabeza),
    # -y profundidad. Centrado/ajuste de cámara lo hace el visor (frame()).
    xyz = np.empty_like(verts, dtype=np.float32)
    xyz[:, 0] = verts[:, 2]      # x = columna x
    xyz[:, 1] = -verts[:, 0]     # y(arriba) = -z (superior)
    xyz[:, 2] = -verts[:, 1]     # z(prof) = -y (anterior)
    vb = base64.b64encode(xyz.tobytes()).decode()
    fb = base64.b64encode(faces.astype(np.uint32).tobytes()).decode()

    artifact = {
        "type": "volume3d",
        "structure": structure, "structure_label": st["label"],
        "title": _t("title.volume") % (st["label"], len(faces)),
        "color": list(st["color"]),
        "n_vertices": int(len(verts)), "n_triangles": int(len(faces)),
        "vertices_b64": vb, "faces_b64": fb,
        "source": _t("source.volume"),
    }
    workdir = os.environ.get("PUPPET_WORKDIR") or os.getcwd()
    try:
        with open(os.path.join(workdir, "volume.volume3d.json"), "w", encoding="utf-8") as f:
            json.dump(artifact, f, ensure_ascii=False)
    except Exception:
        pass
    vox_mm3 = vol["sx"] * vol["sy"] * vol["sz"]
    return {
        "ok": True, "structure": structure, "structure_label": st["label"],
        "n_vertices": int(len(verts)), "n_triangles": int(len(faces)),
        "mask_voxels": voxels, "segmented_volume_ml": round(voxels * vox_mm3 / 1000.0, 1),
        "detail": detail, "rendered_as": _t("rendered.volume"),
        "note": _t("note.volume") % (st["label"], st["lo"], st["hi"], len(faces)),
        "read_only": True, "disclaimer": _t("disclaimer"),
    }


def _segment_structure(args):
    structure = (args.get("structure") or "").strip()
    if structure not in STRUCTURES:
        return {"ok": False, "error": _t("err.structure_invalid") % structure}
    vol = _load_volume()
    hu = vol["hu"]
    st = STRUCTURES[structure]
    mask = _compute_mask(hu, structure)

    voxels = int(mask.sum())
    vox_mm3 = vol["sx"] * vol["sy"] * vol["sz"]
    volume_ml = voxels * vox_mm3 / 1000.0

    # overlay sobre el corte (axial por default), ventana acorde a la estructura
    plane = (args.get("plane") or "axial").strip()
    if plane not in ("axial", "coronal", "sagittal"):
        plane = "axial"
    img_hu, sp_c, sp_r, n, idx = _reslice(vol, plane, args.get("index"))
    # máscara en el mismo plano/índice
    if plane == "coronal":
        m2d = np.flipud(mask[:, idx, :])
    elif plane == "sagittal":
        m2d = np.flipud(mask[:, :, idx])
    else:
        m2d = mask[idx]
    pset = "lung" if structure == "lung" else "bone"
    base = _window(img_hu, PRESETS[pset]["wl"], PRESETS[pset]["ww"])
    rgb = np.stack([base, base, base], axis=-1).astype(np.float32)
    col = np.array(st["color"], dtype=np.float32)
    edge = m2d ^ ndimage.binary_erosion(m2d)            # borde de la máscara
    rgb[m2d] = 0.55 * rgb[m2d] + 0.45 * col              # relleno translúcido
    rgb[edge] = col                                       # contorno sólido
    over = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8))
    if plane != "axial":
        over = over.resize(_to_physical(base, sp_c, sp_r).size, Image.BILINEAR)
    slice_area_mm2 = round(float(m2d.sum()) * sp_c * sp_r, 1)

    fname = _write_png(over, f"segmentation_{structure}.png")
    # artifact imagen (overlay) → La Sala lo rinde
    workdir = os.environ.get("PUPPET_WORKDIR") or os.getcwd()
    artifact = {"type": "imagen", "content": _png_b64(over),
                "alt": _t("alt.segment") % st["label"],
                "title": _t("title.segment") % (st["label"], volume_ml)}
    try:
        with open(os.path.join(workdir, "segmentation.imagen.json"), "w", encoding="utf-8") as f:
            json.dump(artifact, f, ensure_ascii=False)
    except Exception:
        pass

    return {
        "ok": True, "structure": structure, "structure_label": st["label"],
        "hu_threshold": [st["lo"], st["hi"]],
        "mask_voxels": voxels,
        "voxel_volume_mm3": round(vox_mm3, 4),
        "segmented_volume_ml": round(volume_ml, 1),
        "overlay_plane": plane, "overlay_index": idx,
        "slice_mask_area_mm2": slice_area_mm2,
        "image_file": fname, "rendered_as": _t("rendered.segment"),
        "note": _t("note.segment") % (st["label"], st["lo"], st["hi"]),
        "read_only": True, "disclaimer": _t("disclaimer"),
    }


# ── MCP stdio (idéntico a fem/precio/spice) ──────────────────────────────────

def _send(obj):
    sys.stdout.write(json.dumps(obj) + "\n"); sys.stdout.flush()


def _handle(req):
    method = req.get("method", ""); req_id = req.get("id"); params = req.get("params", {})
    if method == "initialize":
        _send({"jsonrpc": "2.0", "id": req_id, "result": {
            "protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
            "serverInfo": {"name": "segmentacion-server", "version": "0.1.0"}}})
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        _send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        name = params.get("name", ""); args = params.get("arguments", {}) or {}
        try:
            if name == "windowing":
                val = _windowing(args)
            elif name == "extract_slice":
                val = _extract_slice(args)
            elif name == "segment_structure":
                val = _segment_structure(args)
            elif name == "render_volume_3d":
                val = _render_volume_3d(args)
            else:
                raise ValueError("unknown tool %s" % name)
            _send({"jsonrpc": "2.0", "id": req_id, "result": {
                "content": [{"type": "text", "text": json.dumps(val, ensure_ascii=False)}],
                "isError": not val.get("ok", True)}})
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
