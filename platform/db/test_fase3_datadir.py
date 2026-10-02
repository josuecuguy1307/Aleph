"""
test_fase3_datadir.py — [Casa 2 · Fase 3 · B3] las escrituras del cliente salen del árbol.

Verde = efecto real: en rol CLIENTE, vault/enc.key/espacios/safety se RESUELVEN (y la
enc.key se ESCRIBE) en el dir de datos del usuario, NO en el árbol de código; en rol
CONTROL, los paths son byte-idénticos al histórico (prod no se mueve).

Red-proof: con el código viejo (vault/espacios/enc.key anclados a `_REPO_ROOT` sin mirar
el rol) `test_cliente_*` rompe (caerían en el árbol) y `test_enc_key_*` escribiría en
`platform/db/secrets/`, no en el tmp del usuario.
"""
import ast
import importlib.util
import os
import sys
from pathlib import Path

import aleph_paths

_REPO_ROOT = Path(aleph_paths.__file__).resolve().parents[1]
_TREE = _REPO_ROOT / "product" / "backend" / "data"


def _load_by_path(modname: str, relpath: str):
    """Carga un módulo por ruta de archivo (sin ensuciar sys.path ni colisionar nombres)."""
    spec = importlib.util.spec_from_file_location(modname, str(_REPO_ROOT / relpath))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _as_client(monkeypatch, datadir: Path):
    monkeypatch.setenv("ALEPH_ROLE", "client")
    monkeypatch.setenv("ALEPH_DATA_DIR", str(datadir))
    monkeypatch.delenv("PUPPET_DB_ENC_KEY", raising=False)


def _as_control(monkeypatch):
    monkeypatch.setenv("ALEPH_ROLE", "control")
    monkeypatch.delenv("ALEPH_DATA_DIR", raising=False)
    monkeypatch.delenv("ALEPH_DATA_ROOT", raising=False)


def test_cliente_escribe_fuera_del_arbol(monkeypatch, tmp_path):
    _as_client(monkeypatch, tmp_path)
    for p in (aleph_paths.vault_path(), aleph_paths.enc_key_path(),
              aleph_paths.espacios_dir(), aleph_paths.safety_dir(),
              aleph_paths.data_root()):
        assert str(p).startswith(str(tmp_path)), f"{p} debería estar bajo {tmp_path}"
        assert _TREE not in p.parents and p != _TREE, f"{p} NO debe caer en el árbol"


def test_control_no_se_mueve(monkeypatch):
    _as_control(monkeypatch)
    assert aleph_paths.data_root() == _TREE
    assert aleph_paths.vault_path() == _TREE / "vault.enc"
    assert aleph_paths.espacios_dir() == _TREE / "espacios"
    assert aleph_paths.safety_dir() == _TREE / "safety"
    assert aleph_paths.enc_key_path() == _REPO_ROOT / "platform" / "db" / "secrets" / "enc.key"


def test_enc_key_se_escribe_en_datadir_y_es_estable(monkeypatch, tmp_path):
    _as_client(monkeypatch, tmp_path)
    import db
    k1 = db._load_or_create_key()
    keyfile = tmp_path / "secrets" / "enc.key"
    assert keyfile.exists(), "la enc.key del cliente debe escribirse en el dir de datos"
    assert _TREE not in keyfile.parents, "la enc.key NO debe quedar en el árbol de código"
    # estable entre 'arranques': segunda resolución = misma clave (no se regenera y deja
    # datos ilegibles). Round-trip real de cifrado para probar que la clave sirve.
    k2 = db._load_or_create_key()
    assert k1 == k2 == keyfile.read_bytes().strip()
    token = db.encrypt_secret("sk-secreto-byok")
    assert db.decrypt_secret(token) == "sk-secreto-byok"


def test_resolver_es_portable_sin_os_uname():
    # os.uname() no existe en Windows (bug B4a, aparte): el resolver de Fase 3 NO debe
    # reintroducirlo — se apoya en sys.platform / os.name. Se mira el AST (no el texto):
    # una llamada real `*.uname` cuenta; el docstring que la nombra, no.
    tree = ast.parse(Path(aleph_paths.__file__).read_text(encoding="utf-8"))
    unames = [n for n in ast.walk(tree)
              if isinstance(n, ast.Attribute) and n.attr == "uname"]
    assert not unames, "aleph_paths debe ser Windows-safe (sin llamar os.uname)"


# ── B1 · Windows-safe: ruta_db delega en aleph_paths (sys.platform/os.name, sin uname) ──

def test_b1_sqlite_db_uname_fallback(monkeypatch, tmp_path):
    """sqlite_db.ruta_db NO crashea cuando os.uname no existe (Windows): la resolución
    delega en aleph_paths.user_data_dir(), que jamás llama uname (fix GAP §2.2)."""
    import sqlite_db
    monkeypatch.delenv("PUPPET_SQLITE_PATH", raising=False)
    monkeypatch.delenv("ALEPH_DATA_DIR", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delattr(os, "uname", raising=False)      # simula Windows: os.uname no existe
    p = sqlite_db.ruta_db()                              # NO debe lanzar AttributeError
    assert p.endswith("aleph.db") and str(tmp_path) in p


def test_b1_sqlite_db_rama_windows(monkeypatch, tmp_path):
    """sys.platform≠darwin + os.name='nt' → usa %APPDATA% (no .local/share, no crash).

    Con os.name parcheado a 'nt', `pathlib.Path()` despacharía a WindowsPath y
    revienta en un POSIX real (3.13) — se fija la clase concreta del OS real: lo
    que se certifica es la RAMA de resolución, no pathlib."""
    import pathlib
    import sqlite_db
    monkeypatch.delenv("PUPPET_SQLITE_PATH", raising=False)
    monkeypatch.delenv("ALEPH_DATA_DIR", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setattr(sys, "platform", "win32")        # la rama de OS la elige aleph_paths
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.delattr(os, "uname", raising=False)
    monkeypatch.setattr(aleph_paths, "Path", pathlib.PosixPath)
    p = sqlite_db.ruta_db()
    assert str(tmp_path / "Roaming") in p and p.endswith("aleph.db")


def test_ruta_db_unificada_con_user_data_dir(monkeypatch, tmp_path):
    """LA invariante del fix GAP §2.2: el .db y la enc.key resuelven al MISMO datadir.
    Antes eran dos resoluciones divergentes — con ALEPH_DATA_DIR aislado, la enc.key
    aterrizaba en el datadir y el .db se iba a ~/Library (medido con lsof)."""
    import sqlite_db
    monkeypatch.delenv("PUPPET_SQLITE_PATH", raising=False)
    monkeypatch.setenv("ALEPH_DATA_DIR", str(tmp_path))
    assert sqlite_db.ruta_db() == str(aleph_paths.user_data_dir() / "aleph.db")
    assert str(aleph_paths.user_data_dir()) == str(tmp_path)


def test_b1_crypto_uname_fallback(monkeypatch):
    """crypto.runtime_master_secret cae a platform.node() en Windows (sin crash)."""
    crypto = _load_by_path("_crypto_fase3_test", "platform/inspection/crypto.py")
    monkeypatch.delenv("PUPPET_VAULT_MASTER", raising=False)
    monkeypatch.delattr(os, "uname", raising=False)      # Windows
    import platform
    assert crypto.runtime_master_secret() == f"puppet-dev-{platform.node() or 'aleph-client'}"


# ── B2 · sys.executable bajo PyInstaller: frozen → Python del sistema, no el .exe ──

def test_b2_no_frozen_usa_sys_executable(monkeypatch):
    """Fuera de frozen (dev/control en Render) → sys.executable, byte-idéntico a hoy."""
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert aleph_paths.python_executable() == sys.executable


def test_b2_frozen_resuelve_python_del_sistema(monkeypatch):
    """Bajo frozen usa un Python del sistema, NUNCA el .exe (sys.executable)."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/opt/aleph/Aleph.exe", raising=False)
    monkeypatch.delenv("PUPPET_PYTHON", raising=False)
    import shutil
    monkeypatch.setattr(shutil, "which", lambda c: "/usr/bin/python3" if c == "python3" else None)
    got = aleph_paths.python_executable()
    assert got == "/usr/bin/python3" and got != sys.executable


def test_b2_frozen_override_puppet_python(monkeypatch):
    """PUPPET_PYTHON gana sobre el autodetectado bajo frozen."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/opt/aleph/Aleph.exe", raising=False)
    monkeypatch.setenv("PUPPET_PYTHON", "/custom/py")
    assert aleph_paths.python_executable() == "/custom/py"
