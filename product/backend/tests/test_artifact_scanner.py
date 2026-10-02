"""RED-TEST del scanner de higiene del artefacto. [Casa 2 · Fase 4 · 4.2.c]

Afinar el scanner (allowlistear la anon-key pública, saltar vendor/) NO puede degenerar en
CALLARLO. Este test lo fija PARA SIEMPRE (no una verificación de una vez):
  - la anon-key de Supabase (pública por diseño) NO frena el push (allowlist POR HASH), pero
  - un JWT DISTINTO (service_role) y un connection-string siguen dando ROJO.
Si alguien "afina" el scanner hasta que deje pasar un secreto real, uno de estos cae en rojo.
"""
import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO / "deploy"))
import scan_secretos  # noqa: E402

# La anon-key REAL del repo (pública) — la MISMA que el scanner allowlistea por hash. Leerla de
# la fuente ata el test al valor vigente: si se rota sin actualizar el allowlist, este test cae.
_CFG = (_REPO / "product" / "app" / "design" / "aleph-config.js").read_text(encoding="utf-8")
_ANON = re.search(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}", _CFG).group(0)

_CLEAN, _NO_PUSHEAR = 0, 2   # códigos de scan_secretos.main


def _scan(tmp_path, files: dict) -> int:
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return scan_secretos.main(str(tmp_path))


def test_allows_the_public_supabase_anon_key(tmp_path):
    """La anon-key pública (por diseño) NO frena el push."""
    assert _scan(tmp_path, {"aleph-config.js": f'anonKey: "{_ANON}"'}) == _CLEAN


def test_still_catches_a_service_role_jwt(tmp_path):
    """Un JWT DISTINTO (service_role) tiene OTRO hash → sigue ROJO. El scanner no se calló."""
    fake = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
            "eyJyb2xlIjoic2VydmljZV9yb2xlIiwiaXNzIjoiZmFrZS10ZXN0In0."
            "FAKEsignature0123456789abcdefFAKEsignature")
    assert fake != _ANON
    assert _scan(tmp_path, {"leak.js": f'const KEY = "{fake}"'}) == _NO_PUSHEAR


def test_still_catches_a_connection_string(tmp_path):
    """Un connection-string con contraseña sigue ROJO."""
    assert _scan(tmp_path, {"cfg.py": 'DB = "postgres://admin:SuperSecret1234@db.host:5432/prod"'}) == _NO_PUSHEAR


def test_skips_vendor_minified_no_false_red(tmp_path):
    """vendor/ (libs de terceros minificadas) se saltea → sin falso rojo por JS minificado."""
    assert _scan(tmp_path, {"vendor/xlsx.full.min.js": 'var Token=+String(w)+"aB3xK9zQ1mN7pR4wT9"'}) == _CLEAN
