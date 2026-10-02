"""disco.py — EL DISCO LLENO SE DICE, NO SE DISFRAZA.

QUÉ PROBLEMA CIERRA, con los tres disfraces medidos el 2026-08-28/29 en la misma máquina:

  · En la app     `[Errno 28]` al escribir un `.json.tmp` salió como HTTP 500, y el modelo
                  se lo tradujo al usuario como «el entorno bloqueó la escritura temporal
                  requerida» — que suena a permisos y manda a buscar donde no es.
  · En el build   el mismo disco lleno sale como `internal error in Code Signing subsystem`.
                  Dos tardes se fueron en eso.
  · En un pack    `cache write failed: [Errno 28]` enterrado entre miles de líneas de log.

Tres superficies, tres mensajes distintos, **ninguno decía «no hay espacio»**. El costo no
es el error: es que manda a investigar la superficie equivocada.

LA REGLA QUE APLICA es la del contrato del repo —FALLO VISIBLE, JAMÁS MUDO— y su forma ya
existía para la DB (`_db_fail_visible` + `/health` lo reporta). Esto es lo mismo para el
disco: una causa TIPADA con su copy, un código HTTP que significa lo que pasa, y `/health`
diciéndolo antes de que reviente algo.

POR QUÉ SE MIRA LA CADENA DE EXCEPCIONES y no el `errno` de arriba: casi nunca llega crudo.
Llega envuelto —`shutil`, `json.dump`, `sqlite3`, un `PermissionError` de un `.tmp` que no se
pudo crear— y el `errno` real está tres `__cause__` más abajo. Mirar sólo la de arriba es no
cazar ninguno de los tres casos de arriba.
"""
from __future__ import annotations

import errno as _errno
import os
import shutil
from typing import Optional

#: La causa, con el mismo vocabulario que el resto de las causas de la casa.
CAUSA = "disco_lleno"

#: El copy que ve una persona. Dice QUÉ pasó y QUÉ hacer — no pide disculpas ni culpa al
#: usuario, y no nombra un `errno` que no le sirve a nadie.
COPY = ("No queda espacio en el disco, así que Aleph no pudo guardar. "
        "Libera espacio y vuelve a intentar: lo que estabas haciendo no se perdió.")

#: Debajo de esto, `/health` deja de decir «ok». No es el umbral del build —que necesita
#: decenas de GB— sino el de la app: con menos que esto, guardar una preferencia o un
#: artefacto ya empieza a fallar.
MINIMO_SANO_BYTES = 2 * 1024 * 1024 * 1024


def es_disco_lleno(exc: BaseException | None) -> bool:
    """¿Esta excepción —o alguna de las que la causaron— es «no queda espacio»?"""
    visto = set()
    while exc is not None and id(exc) not in visto:
        visto.add(id(exc))
        numero = getattr(exc, "errno", None)
        if numero == _errno.ENOSPC:
            return True
        # `OSError` a veces guarda el errno del sistema en `winerror`/`args`; y hay
        # librerías que re-lanzan con el texto y sin el número. El texto es el ÚLTIMO
        # recurso, no el primero, para no acusar a un mensaje que sólo lo menciona.
        if numero is None and isinstance(exc, OSError):
            texto = str(exc).lower()
            if "no space left on device" in texto or "errno 28" in texto:
                return True
        exc = exc.__cause__ or exc.__context__
    return False


def libre_bytes(ruta: Optional[str] = None) -> Optional[int]:
    """Bytes libres en el volumen donde Aleph escribe. `None` si no se pudo mirar —y eso
    NO se convierte en alarma: no saber no es lo mismo que estar lleno."""
    try:
        if ruta is None:
            from aleph_paths import user_data_dir
            ruta = str(user_data_dir())
        return shutil.disk_usage(ruta).free
    except Exception:
        return None


def estado() -> dict:
    """Lo que `/health` publica. `estado` es `ok`, `bajo` o `desconocido` — nunca inventa."""
    libre = libre_bytes()
    if libre is None:
        return {"estado": "desconocido"}
    return {
        "estado": "ok" if libre >= MINIMO_SANO_BYTES else "bajo",
        "libre_gb": round(libre / (1024 ** 3), 1),
        "minimo_gb": round(MINIMO_SANO_BYTES / (1024 ** 3), 1),
    }
