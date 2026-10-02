#!/usr/bin/env python3
"""verify_citas_diseno_repair.py — LAS CITAS DEL DISEÑO SON VERIFICABLES.

`DISEÑO-REPAIR-v1.md` afirma cosas sobre el árbol y cada una lleva su `archivo:línea`. Un
número de línea envejece: basta un commit que agregue diez líneas arriba para que la cita
apunte a otra cosa, y un diseño con citas podridas es peor que uno sin citas — parece
verificable y no lo es. (Pasó al escribirlo: `clave_de` decía :164 y estaba en :217, porque
D5 le había metido 84 líneas a `dueno.py`.)

Tolerancia de ±3 líneas a propósito: una cita apunta a un BLOQUE, no a un carácter.

    product/backend/.venv/bin/python platform/inspection/verify_citas_diseno_repair.py
"""
from pathlib import Path
# ⚠️ LA RAÍZ SALE DE ESTE ARCHIVO, NO DE UNA RUTA ESCRITA A MANO.
#
# Acá decía `Path("<repo>")`: un worktree FIJO, y distinto del que
# uno está tocando. O sea que la vara verificaba las citas de OTRA copia del repo — daba
# verde sobre código que no era el que iba a mergearse, y hubiera dado verde sobre archivos
# que en esta rama ya no existen. Una vara que mide otro árbol no mide nada.
R = Path(__file__).resolve().parents[2]
# (archivo, línea o rango, subcadena que TIENE que estar ahí)
CITAS = [
 ("platform/inspection/dueno.py", 925, "el dueño haciendo su trabajo, no repair"),
 ("platform/inspection/dueno.py", 926, "_parece_muerta"),
 ("platform/inspection/dueno.py", 927, 'self._contadores["muertes"] += 1'),
 ("platform/inspection/dueno.py", 928, 'motivo="murió y se pidió de nuevo"'),
 ("platform/inspection/dueno.py", 1004, "def _parece_muerta"),
 ("platform/inspection/dueno.py", 1152, "def _cerrar"),
 ("platform/inspection/dueno.py", 1165, "self._tabla.pop"),
 ("platform/inspection/dueno.py", 1193, '"eventos"'),
 ("platform/inspection/dueno.py", 217, "def clave_de"),
 ("platform/inspection/dueno.py", 78,  "OCIOSIDAD_S"),
 ("platform/inspection/dueno.py", 86,  "MAX_VIVAS"),
 ("platform/inspection/dueno.py", 110, "def encendido"),
 ("platform/inspection/dueno.py", 1140, "def apagar_entidad"),
 ("platform/inspection/dueno.py", 228, "class _Libro"),
 ("platform/inspection/dueno.py", 1202, "def barrer_al_arrancar"),
 ("platform/inspection/dueno.py", 624, "def call_tool"),
 ("platform/inspection/dueno.py", 1181, "nacida_en"),
 ("platform/inspection/dueno.py", 1196, "def _volcar"),
 ("platform/inspection/transporte_sdk.py", 296, "_murio.set()"),
 ("platform/inspection/transporte_sdk.py", 251, "def murio"),
 ("platform/inspection/transporte_sdk.py", 264, "def soltar_escritura"),
 ("platform/inspection/transporte_sdk.py", 581, "def diagnostico"),
 ("platform/inspection/transporte_sdk.py", 592, "stderr"),
 ("platform/inspection/transporte_sdk.py", 594, "no expuesto"),
 ("platform/inspection/transporte_sdk.py", 223, "MAX_BYTES"),
 ("platform/inspection/transporte_sdk.py", 208, "class _CapturaStderr"),
 ("product/backend/app/phase1/motor_verdad.py", 129, "CAUSAS = frozenset"),
 ("product/backend/app/phase1/motor_verdad.py", 90, "PROVEEDOR_CAIDO"),
 ("product/backend/app/phase1/motor_verdad.py", 89, "FALLA_DE_ALEPH"),
 ("platform/assembler/errores_modelo.py", 113, "_REINTENTABLES"),
 ("platform/assembler/errores_modelo.py", 189, "reintentable"),
 ("platform/assembler/errores_modelo.py", 190, "retry_after_s"),
 ("platform/inspection/traductor_errores.py", 87, "def codigo_de"),
 ("platform/inspection/traductor_errores.py", 112, "def contesto"),
 ("platform/inspection/traductor_errores.py", 131, "def causa_de_corte"),
 ("platform/inspection/traductor_errores.py", 182, "def detalle_de_arranque"),
 ("platform/inspection/traductor_errores.py", 228, "def evidencia_de_arranque"),
 ("product/backend/app/phase1/diagnostico_conectores.py", None, "SERVIDOR_INCOMPATIBLE"),
 ("product/backend/app/phase1/diagnostico_conectores.py", None, "normalizar_camino"),
 ("product/backend/app/phase1/centro_conexiones.py", 20, "mano_humana"),
 ("product/backend/app/phase1/centro_conexiones.py", 24, "mano_humana"),
 ("product/backend/app/phase1/centro_conexiones.py", 1118, "mano_humana"),
 # [ADAPTADOR 2026-08-04] Las tres citas apuntaban a `conectores.ui.js`, demolido con las
 # UIs viejas. Las MISMAS verdades siguen en el árbol, en la superficie del adaptador:
 # el botón sale de repair (`data-accion`), la sesión vencida es su propia causa, y sacar
 # una credencial muestra el impacto antes de confirmar. Se re-citan donde viven ahora en
 # vez de borrarse: una cita perdida es una regla que deja de estar amarrada a nada.
 ("product/app/design/conectores/superficie.js", None, "data-accion"),
 ("product/app/design/conectores/superficie.js", None, "La sesión venció"),
 ("product/app/design/conectores/montaje.js", None, "sacarLlave"),
 # [ACTA DEL CATÁLOGO LOCAL · 2026-08-04] Las cuatro afirmaciones de la ley, amarradas al
 # árbol. Una ley que no se puede verificar es una intención.
 ("product/app/design/conectores/widget.js", None, "export function pertenencia"),
 ("product/app/design/conectores/superficie.js", None, "pintarAduana"),
 ("product/backend/app/phase1/centro_conexiones.py", None, "def re_verificar_local"),
 ("product/backend/app/phase1/conexiones_verificador.py", None, "solo_conexion"),
 ("platform/assembler/restaurador.py", 30, "LA LÁPIDA"),
 ("platform/assembler/restaurador.py", 111, "stderr"),
 ("platform/assembler/restaurador.py", 193, "habilitado"),
 ("product/backend/app/phase1/conexiones_repo.py", None, "def upsert_entidad"),
 ("product/backend/app/phase1/conexiones_repo.py", None, "Solo pisa los campos"),
 ("platform/connectors/oauth_flow.py", None, "expira_en"),
 ("product/backend/app/main.py", 173, "barrer_al_arrancar"),
 ("product/backend/app/main.py", None, "apagar_todo"),
 ("product/backend/app/phase1/conexiones_verificador.py", None, "def verificar_uno"),
 ("product/backend/app/phase1/conexiones_verificador.py", None, "no cableado por este verificador"),
 ("product/backend/app/phase1/conexiones_verificador.py", None, "rpc_timeout"),
 ("product/backend/app/phase1/conexiones_verificador.py", None, "rpc_timeout=45"),
 ("platform/inspection/dueno.py", 963, "rpc_timeout"),
 ("platform/inspection/dueno.py", 173, "Del hash NO sale"),
 ("product/backend/app/phase1/conexiones_verificador.py", 89, "sin_respuesta"),
 ("product/backend/app/phase1/conexiones_verificador.py", 85, "arranque"),
]
malas = 0
for arch, ln, sub in CITAS:
    p = R / arch
    lineas = p.read_text(errors="replace").splitlines()
    if ln is None:
        # CITA SIN NÚMERO DE LÍNEA: se busca en todo el archivo.
        #
        # ⚠️ ES A PROPÓSITO Y NO ES UNA DEBILIDAD. Una cita con número amarra el diseño a un
        # renglón, y eso se rompe cada vez que alguien agrega un comentario arriba — lo que
        # entrena a la gente a "arreglar" la vara moviendo el número en vez de mirar si la
        # regla sigue viva. Cuando lo que importa es que la regla ESTÉ en ese archivo (y no
        # exactamente dónde), el número sobra y su ausencia es más honesta que un número que
        # todos saben que hay que retocar.
        if not any(sub in l for l in lineas):
            malas += 1
            print(f"  ✗ {arch} — no encuentro {sub!r} en todo el archivo")
        continue
    # tolerancia ±3 líneas: una cita apunta a un bloque, no a un carácter
    ventana = lineas[max(0, ln-4):ln+3]
    if not any(sub in l for l in ventana):
        malas += 1
        print(f"  ✗ {arch}:{ln} — no encuentro {sub!r}")
        print(f"      línea real: {lineas[ln-1][:100]!r}")
print(f"\n{len(CITAS)-malas}/{len(CITAS)} citas verifican" + (" · TODO VERDE" if not malas else f" · {malas} MALAS"))
import sys
sys.exit(0 if not malas else 1)
