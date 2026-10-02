"""
aleph_paths.py — DÓNDE escribe el runtime. [Casa 2 · Fase 3 · B3]

El problema que cierra: el backend escribía sus datos DENTRO del árbol de código
(`_REPO_ROOT/product/backend/data/...`, `platform/db/secrets/enc.key`). Bajo un
bundle de PyInstaller ese árbol es de SÓLO LECTURA y, peor, se reemplaza entero al
actualizar (se llevaría los datos del usuario puestos). Es el mismo problema que
`platform/db/sqlite_db.py::_db_path()` ya resolvió para el `.db` — este módulo lo
generaliza al resto de las escrituras (vault, enc.key, espacios, safety).

Contrato por ROL (la frontera de `platform/role.py`):
  - CLIENTE  → el dir de datos del usuario, FUERA del árbol (co-ubicado con el
               `aleph.db` que ya escribe `sqlite_db.py`: un solo dir `Aleph/`).
  - CONTROL  → el comportamiento HISTÓRICO exacto (dentro del árbol). Producción
               declara `ALEPH_ROLE=control`, así que prod NO se mueve ni un byte.

Portable a propósito: elige el dir por `sys.platform`/`os.name`, NUNCA con
`os.uname()` (que no existe en Windows — ese es el bug B4a, aparte). El override
`ALEPH_DATA_DIR` gana siempre (tests/ops apuntan a un tmp).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# aleph_paths.py vive en platform/ → parents[1] es la raíz del árbol de código.
_REPO_ROOT = Path(__file__).resolve().parents[1]

# Raíces HISTÓRICAS dentro del árbol (lo que usa el CONTROL — no tocar prod).
_TREE_DATA = _REPO_ROOT / "product" / "backend" / "data"        # vault, espacios, safety
_TREE_DB_SECRETS = _REPO_ROOT / "platform" / "db" / "secrets"    # enc.key


def is_client() -> bool:
    """¿Este proceso es el cliente? Sin asumir que `platform/` esté en el sys.path.

    Fail-safe a CONTROL: si el rol no se puede resolver, se comporta como control
    (mantiene el árbol) — nunca redirige por error a un dir que control no espera.
    """
    try:
        import role
    except ImportError:
        plat = str(Path(__file__).resolve().parent)  # platform/
        if plat not in sys.path:
            sys.path.insert(0, plat)
        try:
            import role
        except Exception:
            return False
    try:
        return role.current() == "client"
    except Exception:
        return False


def user_data_dir() -> Path:
    """Dir de datos del usuario para el CLIENTE, FUERA del árbol de código.

    Precedencia (idéntica en espíritu a `sqlite_db._db_path`, con el que se co-ubica):
      1. `ALEPH_DATA_DIR` — override explícito (tests/ops).
      2. El lugar estándar por OS:
         macOS   → ~/Library/Application Support/Aleph
         Windows → %APPDATA%\\Aleph   (o ~/AppData/Roaming/Aleph)
         Linux   → $XDG_DATA_HOME/Aleph  (o ~/.local/share/Aleph)
    Crea el dir si no existe. `Aleph` (mayúscula) en todos: mismo dir que `aleph.db`.
    """
    env = (os.environ.get("ALEPH_DATA_DIR") or "").strip()
    if env:
        d = Path(env)
    else:
        base = os.environ.get("XDG_DATA_HOME")
        if not base:
            home = Path(os.path.expanduser("~"))
            if sys.platform == "darwin":
                base = str(home / "Library" / "Application Support")
            elif os.name == "nt":
                base = os.environ.get("APPDATA") or str(home / "AppData" / "Roaming")
            else:
                base = str(home / ".local" / "share")
        d = Path(base) / "Aleph"
    d.mkdir(parents=True, exist_ok=True)
    return d


def data_root() -> Path:
    """Raíz de escritura de datos del runtime (vault, espacios, safety).

    CLIENTE → `user_data_dir()`. CONTROL → `product/backend/data` (histórico).
    """
    return user_data_dir() if is_client() else _TREE_DATA


def vault_path() -> Path:
    """`vault.enc` (credenciales cifradas del runtime)."""
    return data_root() / "vault.enc"


def espacios_dir() -> Path:
    """Dir de espacios (índice JSONL + workdir por espacio)."""
    return data_root() / "espacios"


def rag_dir() -> Path:
    """Raíz de los índices RAG del usuario (`<data_root>/rag/<user>/<agente>/`).

    ⚠️ EL BUNDLE ES SÓLO LECTURA. Esto vivía en `product/backend/data/rag`, resuelto con
    `parents[4]` — que bajo PyInstaller apunta DENTRO de `_MEIPASS`, el temp del bundle.
    Efecto medido: los índices se escribían en un directorio que se borra al cerrar la app,
    así que el usuario subía sus documentos y desaparecían. Y rompía la ley que el propio
    módulo declara: «el usuario es dueño de su índice». Un índice que muere al cerrar no es
    de nadie.

    Misma raíz que la base y el llavero: si el usuario respalda su carpeta de datos, se
    lleva TODO —conexiones, credenciales e índices— y no tres mitades.
    """
    return data_root() / "rag"


def synth_belts_dir() -> Path:
    """Belts forjados por el usuario (BYO-MCP) + sus credenciales por principal."""
    return data_root() / "synth_belts"


def resolver_cache_dir() -> Path:
    """Caché del resolver de MCPs. Se puede perder sin drama —se recalcula— pero escribir
    en el bundle no la hace efímera: la hace IMPOSIBLE (el temp es de sólo-lectura efectiva
    para el próximo arranque, que ya no lo encuentra)."""
    return data_root() / "resolver_cache"


def outbox_path() -> Path:
    """Cola de mails salientes (`outbox/mails.jsonl`)."""
    return data_root() / "outbox" / "mails.jsonl"


def procesos_path() -> Path:
    """El registro de procesos MCP vivos del dueño (`procesos.jsonl`).

    Efímero por naturaleza —no sobrevive un reboot— pero NO puede vivir bajo el bundle: si
    quedara en `_MEIPASS`, el próximo arranque no encontraría lo que dejó el anterior y el
    barrido de huérfanos no tendría a qué mirar, que es justo su razón de ser
    (`DISEÑO-DUEÑO-v1.md` §3.1).

    Va al lado de `outbox_path()` por el mismo motivo que aquél: es una cola del proceso,
    no un dato del usuario, pero se escribe y se lee y por eso necesita un dónde estable."""
    return data_root() / "procesos.jsonl"


def safety_dir() -> Path:
    """Sub-árbol de la capa de safety (audit, kill-switch, rate-state)."""
    return data_root() / "safety"


def python_executable() -> str:
    """El intérprete Python para lanzar servidores/scripts MCP por subprocess.
    [Casa 2 · Fase 3 · B2]

    Bajo PyInstaller (`sys.frozen`) `sys.executable` es el .exe del cliente, NO un
    Python — spawnear un `.py` con él falla. Ahí se resuelve un Python del sistema.
    FUERA de frozen (dev, y CONTROL en Render que no está congelado) devuelve
    `sys.executable` tal cual — comportamiento actual, byte-idéntico. Override
    explícito: `PUPPET_PYTHON`. Último recurso si no hay Python en PATH: `sys.executable`
    (best-effort antes que crashear el resolver).
    """
    if not getattr(sys, "frozen", False):
        return sys.executable
    override = (os.environ.get("PUPPET_PYTHON") or "").strip()
    if override:
        return override
    import shutil
    for cand in ("python3", "python"):
        found = shutil.which(cand)
        if found:
            return found
    return sys.executable


def enc_key_path() -> Path:
    """Keyfile Fernet del cifrado BYOK at-rest.

    CLIENTE → `<user_data_dir>/secrets/enc.key` (fuera del árbol; también cierra la
    higiene: no puede commitearse ni viajar en el artefacto). CONTROL → el histórico
    `platform/db/secrets/enc.key`. El valor por env (`PUPPET_DB_ENC_KEY`) sigue
    ganando aguas arriba, en `db.py` — este path sólo aplica al modo auto-generado.
    """
    if is_client():
        return user_data_dir() / "secrets" / "enc.key"
    return _TREE_DB_SECRETS / "enc.key"


# ── DÓNDE se LEE lo empaquetado (código y datos que viajan) ────────────────────
# [Casa 2 · Fase 4 · 4.1] Distinto de user_data_dir() (DÓNDE se ESCRIBE): esto es la
# raíz de los recursos que viajan en el artefacto.

#: Segmentos top-level del árbol de código. Sirven para reubicar una ruta
#: repo-relativa al bundle sin depender del `parents[N]` (que apunta FUERA de
#: `_MEIPASS` bajo PyInstaller). Ninguno aparece en el prefijo del home/tmp de build.
_TOP_LEVEL = frozenset({
    "platform", "product", "catalog", "org", "infra", "deploy", "eval", "audit", "qa",
})


def resource_root() -> Path:
    """Raíz de los recursos EMPAQUETADOS. Bajo PyInstaller (`sys.frozen`+`sys._MEIPASS`)
    los recursos se extraen a `_MEIPASS`; fuera de frozen es la raíz del árbol de código.
    """
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
    return _REPO_ROOT


def load_module_by_path(name: str, path):
    """Carga un módulo `.py` por RUTA, frozen-aware. [Casa 2 · Fase 4 · 4.1]

    Reemplaza el idiom repetido `spec_from_file_location(name, path)` +
    `module_from_spec` + `exec_module`, que rompe bajo PyInstaller porque `path` sale
    de un `parents[N]` que apunta FUERA del bundle (a `<dist>/…`, inexistente).

    - **dev** (no frozen): usa `path` tal cual → comportamiento **byte-idéntico**.
    - **frozen**: reubica el sufijo repo-relativo de `path` (desde el primer segmento
      top-level: `platform/`, `product/`, …) a `resource_root()` = `_MEIPASS`. El `.py`
      objetivo tiene que viajar como `datas` del `.spec`.

    NO se aplica a los 8 dynamic-loads de `platform/inspection/**` (salen con Motor B,
    D-A): ésos conservan su idiom a propósito.

    ⚠️ DOS REGLAS PARA EL MÓDULO QUE SE CARGA ASÍ. Las dos salen de que este loader NO
    registra el módulo en `sys.modules` (`module_from_spec` no lo hace, y registrarlo acá
    tampoco es gratis: media docena de los targets se llaman `db`, `session`,
    `connections`, `assembler` — nombres que TAMBIÉN son importables por `pathex`, así que
    el registro pisaría el módulo real bajo la misma clave). Las dos fallan mudo o tarde,
    que es por qué están escritas acá y no en un doc aparte: acá se toma la decisión.

    1. **Ni un `@dataclass` adentro.** El módulo abre con `from __future__ import
       annotations` (todo el árbol lo hace), así que las anotaciones son strings y
       `@dataclass` tiene que resolverlas contra los globals del módulo:
       `dataclasses.py:757` hace `sys.modules.get(cls.__module__).__dict__` SIN guard.
       Como acá `.get()` devuelve `None`, revienta con
       `AttributeError: 'NoneType' object has no attribute '__dict__'` — en el import, no
       al usar la clase, o sea que se lleva puesto al módulo entero. Verificado en 3.13.11:
       `@dataclass` solo, o con `slots=True`, o con `field(default_factory=…)`, anda; con
       `from __future__ import annotations` NO. Usá una clase pelada con `__slots__`
       (`restaurador.PiezaRestaurada` es el ejemplo).

    2. **Va declarado en el `.spec` o se pierde CALLADO.** `Analysis` descubre por import
       estático; una carga por ruta le es invisible. El `.py` viaja como `datas` (ya está,
       vía `_TARGET_DIRS`) pero además el nombre tiene que estar en `_TARGET_MODULES`
       (`deploy/fase4/aleph_sidecar.spec:32`) para que viaje su cascada de dependencias.
       Sin eso el bundle se arma sin error y el fallo aparece recién en runtime, en la
       máquina del usuario. Es el caso índice FIX-P1B (`assembler.py` afuera del .app →
       «Error del proveedor»), y volvió a pasar con `multiagente` y con `restaurador`.
    """
    import importlib.util

    p = Path(path)
    if getattr(sys, "frozen", False):
        raiz = resource_root()
        # ⚠️ SI YA ESTÁ ADENTRO DE LA RAÍZ, NO SE REUBICA. [TANDA 3]
        #
        # La reubicación busca el PRIMER segmento de `_TOP_LEVEL` y le antepone
        # `resource_root()`. Con onefile eso no podía fallar: `_MEIPASS` es
        # `/var/folders/…/_MEIxxxx`, que jamás contiene `platform`, `deploy`, `qa`…
        # Con ONEDIR la raíz es una ruta REAL del disco, y si el `.app` vive bajo una
        # carpeta llamada como un ancla la ruta se DUPLICA. Medido dos veces el
        # 2026-08-22, las dos con el sidecar muriendo en `connect_engine.py`:
        #
        #   …/deploy/fase4/_medicion_sidecar/_internal/deploy/fase4/…/platform/connectors/…
        #   …/Contents/Frameworks/deploy/fase4/…/Contents/Frameworks/platform/connectors/…
        #
        # Un `path` que YA cuelga de la raíz no necesita reubicación —es el caso normal en
        # onedir, donde el llamador arma `resource_root()/platform/…`— y reubicarlo es
        # exactamente lo que rompe. Esto no cambia una coma del comportamiento en onefile:
        # allá ningún `path` cuelga de `_MEIPASS` antes de reubicar.
        ya_adentro = False
        try:
            p.resolve().relative_to(raiz.resolve())
            ya_adentro = True
        except (ValueError, OSError):
            ya_adentro = False
        if not ya_adentro:
            parts = p.parts
            idx = next((i for i, seg in enumerate(parts) if seg in _TOP_LEVEL), None)
            if idx is not None:
                p = raiz.joinpath(*parts[idx:])
    spec = importlib.util.spec_from_file_location(name, str(p))
    if spec is None or spec.loader is None:
        raise ImportError(f"load_module_by_path: no se pudo cargar {name!r} desde {p}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── El PLANO DE CONTROL (para el puente cliente→control) ───────────────────────
# [Casa 2 · Fase 4 · 4.2.d] El cliente le manda la FORJA (construir un MCP nuevo = premium; el
# moat vive server-side, D-A). Necesita saber a dónde.
_CONTROL_URL_DEFAULT = "https://aleph-prod.onrender.com"


def control_url() -> str:
    """URL del plano de control. Jerarquía igual que el resto de aleph_paths: la env
    `ALEPH_CONTROL_URL` GANA; si no, el default de prod HARDCODEADO. Por qué hardcodeado: el
    usuario del `.exe` no setea env vars — sin default, el premium no andaría out-of-the-box; y
    la URL NO es secreta (se ve en el tráfico igual). Sin barra final."""
    return ((os.environ.get("ALEPH_CONTROL_URL") or "").strip() or _CONTROL_URL_DEFAULT).rstrip("/")


__all__ = [
    "is_client", "user_data_dir", "data_root",
    "vault_path", "espacios_dir", "rag_dir", "synth_belts_dir",
    "resolver_cache_dir", "outbox_path", "procesos_path", "safety_dir", "enc_key_path",
    "python_executable",
    "resource_root", "load_module_by_path",
    "control_url",
]
