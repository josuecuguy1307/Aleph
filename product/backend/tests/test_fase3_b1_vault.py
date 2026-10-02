"""[Casa 2 · Fase 3 · B1] main.get_vault Windows-safe.

En Windows os.uname no existe → AttributeError. get_vault() debe caer al fallback
(platform.node()) y construir el vault SIN crashear, escribiéndolo en el dir de datos
del usuario (B3). Red-proof: sin el try/except de B1, `os.uname()` lanzaría y get_vault
reventaría en Windows.
"""
import os


def test_get_vault_uname_fallback_en_windows(monkeypatch, tmp_path):
    import app.main as m
    monkeypatch.setattr(m, "_vault", None)                  # forzar recompute del singleton
    monkeypatch.setenv("ALEPH_ROLE", "client")
    monkeypatch.setenv("ALEPH_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("PUPPET_VAULT_MASTER", raising=False)
    monkeypatch.delattr(os, "uname", raising=False)         # simula Windows: os.uname ausente

    v = m.get_vault()                                        # NO debe lanzar AttributeError
    assert v is not None
    v.put("k", "val")                                        # fuerza la escritura del vault
    assert (tmp_path / "vault.enc").exists()                 # y cae en el datadir (B3), no el árbol
