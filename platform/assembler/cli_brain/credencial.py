"""credencial.py — la llave de instancia del server BYO-CLI (:8926).

QUÉ CIERRA
----------
El `:8926` bindea loopback y ya se defiende del navegador: valida el header `Host` contra
la lista de loopback (anti DNS-rebinding) y **rechaza si viene `Origin`**, porque un cliente
local legítimo no lo manda y un browser cross-site sí (`server.py:163-168`). Eso para el
drive-by, que era la amenaza de clase Ollama/LM-Studio.

Lo que NO para es **otro proceso local**: un script del usuario, o algo que se coló en la
máquina, puede POSTear sin `Origin` y quemarle la ventana de la suscripción — o peor, hablar
con su cerebro. El propio `recipe_assembler.py:2904` ya nombraba esta amenaza al explicar por
qué no le manda la key del dev al puerto: *«evita que otro proceso local que bindee el puerto
la capture»*. Faltaba el otro lado: que el puerto sepa quién le habla.

Patrón tomado de OpenWork (`managed-opencode.ts:70-78`), que arranca su `opencode serve` con
un usuario y una clave aleatorios por instancia inyectados por env. Acá el mecanismo es una
llave por instalación en un archivo `0600`, y la razón de que sea archivo y no env es concreta.

POR QUÉ ARCHIVO Y NO MEMORIA
----------------------------
Una segunda instancia de Aleph **no crea un listener duplicado: reutiliza el que ya responde**
(`lifecycle.py`, modo `shared`). Una llave en memoria o en el env del primer proceso sería
ilegible para el segundo, y todas sus llamadas darían 401 — o sea que asegurar el puerto
rompería la multi-instancia, que es justamente una garantía que este módulo ya daba.

Con un archivo, el que reutiliza la lee. `0600` y bajo el directorio de datos del usuario es
la misma mitigación que ya usa la casa para el material sensible en disco.

EL GATE LO ENCIENDE EL DUEÑO DEL CICLO DE VIDA, NO EL DISCO
-----------------------------------------------------------
La llave viaja **atada al server** (`create_server(..., llave=…)`), no se lee del archivo en
cada request. La primera versión hacía lo segundo y estaba mal: el archivo es por INSTALACIÓN,
así que en cuanto el producto creaba su llave, todo server de esta máquina empezaba a
exigirla — incluidos los efímeros que levantan las varas, que no tienen cómo saberla. Medido:
dos varas en rojo (`verify_tool_choice`, `verify_cli_slots`).

Quien enciende el gate es `lifecycle.start()`, que es el camino del producto: la `.app`
SIEMPRE tiene llave. Un `create_server()` pelado —una vara— queda abierto, que es lo correcto:
la amenaza es el puerto del producto, no un puerto efímero que muere con el test.
"""
from __future__ import annotations

import os
import secrets
import stat
from pathlib import Path
from typing import Optional

#: El env manda sobre el archivo: es cómo `start_caso3_stack.sh` —donde el :8926 es un
#: proceso APARTE— puede compartir la llave con el backend sin tocar disco.
ENV_LLAVE = "PUPPET_CLI_BRAIN_TOKEN"

_NOMBRE = "cli_brain.token"


_aviso_dado = False


def _ruta() -> Optional[Path]:
    try:
        import aleph_paths                                    # type: ignore
        return Path(aleph_paths.data_root()) / _NOMBRE
    except Exception as exc:                                  # noqa: BLE001 — sin paths, sin llave
        # FALLO VISIBLE, JAMÁS MUDO. Sin `aleph_paths` no hay dónde leer la llave, y el
        # cliente sale a hablarle al :8926 sin `Authorization` — o sea 401 y ninguna pista
        # de por qué. «No hay llave configurada» y «no pude ni buscarla» son dos estados
        # distintos y el segundo tiene que doler. Una sola vez por proceso: esto puede
        # correr por turno y un log por turno es ruido, no señal.
        global _aviso_dado
        if not _aviso_dado:
            _aviso_dado = True
            print(f"[cli_brain] no pude resolver dónde vive la llave de instancia "
                  f"({type(exc).__name__}: {exc}); si el :8926 la exige, este proceso va a "
                  f"recibir 401", file=__import__("sys").stderr, flush=True)
        return None


def leer() -> str:
    """La llave de esta instalación, o `""` si no hay. Nunca falla."""
    del_env = str(os.environ.get(ENV_LLAVE) or "").strip()
    if del_env:
        return del_env
    ruta = _ruta()
    if ruta is None:
        return ""
    try:
        return ruta.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def asegurar() -> str:
    """La llave, creándola si no estaba. La llama el dueño del ciclo de vida.

    Idempotente: si ya hay una —en el env o en disco— se devuelve ESA. Dos instancias que
    arrancan juntas tienen que terminar con la misma, porque la segunda va a reutilizar el
    listener de la primera.
    """
    ya = leer()
    if ya:
        return ya
    ruta = _ruta()
    if ruta is None:
        return ""
    nueva = secrets.token_urlsafe(32)
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        # Se crea con 0600 DESDE EL PRINCIPIO: escribir y después hacer chmod deja una
        # ventana —corta, pero real— en la que el archivo es legible por todos.
        fd = os.open(str(ruta), os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                     stat.S_IRUSR | stat.S_IWUSR)
        try:
            os.write(fd, nueva.encode("utf-8"))
        finally:
            os.close(fd)
        return nueva
    except FileExistsError:
        # Otra instancia la creó entre el `leer()` y el `open`. La suya vale.
        return leer()
    except OSError:
        return ""


def coincide(cabecera_authorization: Optional[str], esperada: str = "") -> bool:
    """¿El `Authorization` que llegó trae la llave de esta instalación?

    Sin llave configurada devuelve `True`: el server no exige lo que no tiene (ver cabecera).
    La comparación es de tiempo constante — `secrets.compare_digest`— porque un `==` sobre
    strings corta en el primer byte distinto y le regala la llave a quien mida.
    """
    if not esperada:
        return True
    dada = str(cabecera_authorization or "").strip()
    if dada.lower().startswith("bearer "):
        dada = dada[7:].strip()
    if not dada:
        return False
    return secrets.compare_digest(dada, esperada)


__all__ = ["ENV_LLAVE", "asegurar", "coincide", "leer"]
