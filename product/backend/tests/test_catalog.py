"""
test_catalog.py — Tests for GET /catalog/{nicho}

Uses the REAL finanzas catalog (no mocks).
"""

import pytest
from fastapi.testclient import TestClient

from tests.conftest import CATALOG_ROOT


class TestCatalogEndpoint:
    """GET /catalog/{nicho} — parametrizable nicho, tier gating."""

    def test_catalog_finanzas_returns_200(self, client: TestClient):
        resp = client.get("/catalog/finanzas")
        assert resp.status_code == 200

    def test_catalog_finanzas_has_templates(self, client: TestClient):
        resp = client.get("/catalog/finanzas")
        data = resp.json()
        assert data["nicho"] == "finanzas"
        assert data["total"] > 0
        assert len(data["templates"]) > 0

    def test_catalog_template_has_required_fields(self, client: TestClient):
        resp = client.get("/catalog/finanzas")
        templates = resp.json()["templates"]
        required = {"id", "nombre", "descripcion", "tier", "friccion", "surgery_params"}
        for t in templates:
            missing = required - set(t.keys())
            assert not missing, f"Template {t.get('id')} missing fields: {missing}"

    def test_catalog_template_friccion_is_valid(self, client: TestClient):
        """friccion must be 'cero-friccion' or 'gateado'."""
        resp = client.get("/catalog/finanzas")
        for t in resp.json()["templates"]:
            assert t["friccion"] in ("cero-friccion", "gateado"), (
                f"Template {t['id']} has invalid friccion: {t['friccion']}"
            )

    def test_catalog_template_surgery_params_from_real_config(self, client: TestClient):
        """surgery_params must come from the real config.json, not be empty for t01."""
        resp = client.get("/catalog/finanzas")
        templates = {t["id"]: t for t in resp.json()["templates"]}
        t01 = templates.get("t01-cierre-mensual")
        assert t01 is not None, "t01-cierre-mensual must be in catalog"
        # Real config has surgery_params with input_file, output_file, etc.
        assert "input_file" in t01["surgery_params"]

    def test_catalog_unknown_nicho_returns_404(self, client: TestClient):
        resp = client.get("/catalog/nicho-que-no-existe-xyz")
        assert resp.status_code == 404

    def test_catalog_nicho_is_path_param_parametrizable(self, client: TestClient):
        """The endpoint must NOT hardcode 'finanzas' — other nichos must 404 cleanly."""
        resp = client.get("/catalog/ingenieria-mecanica")
        # This nicho may or may not exist — either 200 or 404 is acceptable,
        # but it must NOT return 500 (no hardcoded finanzas check)
        assert resp.status_code in (200, 404)

    # ── Tier gating · Step 5 · P8 ──────────────────────────────────────────
    # Portados del AccountStore (SQLite) muerto: ahora el tier sale de POSTGRES y de
    # la SESIÓN. Se saltan si no hay Postgres: el gating es lo que se prueba, y sin
    # DB no hay cuenta que gatear.

    @staticmethod
    def _sesion_con_tier(tier: str):
        """Crea una cuenta REAL en Postgres con ese tier y devuelve (token, uid)."""
        import uuid as _uuid
        from app.phase1 import repo
        conn = repo.get_conn()
        u = repo.get_or_create_user(
            conn, f"cat-{tier}-{_uuid.uuid4().hex[:8]}@probe.local", "Sonda catálogo")
        if tier != "free":
            repo.set_tier(conn, u["id"], tier, reason="test:catalogo")
        tok = repo.mint_session(u["id"])
        conn.close()
        return tok, u["id"]

    @staticmethod
    def _borrar(uid):
        from app.phase1 import repo
        conn = repo.get_conn()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE id = %s::uuid", (uid,))
        conn.commit()
        conn.close()

    @pytest.mark.db
    @pytest.mark.parametrize("tier,ve_tecnico", [
        ("free", False), ("basico", False), ("tecnico", True),
    ])
    def test_catalog_gatea_por_el_tier_de_la_SESION(self, client: TestClient,
                                                    tier, ve_tecnico):
        try:
            tok, uid = self._sesion_con_tier(tier)
        except Exception:
            pytest.skip("Postgres puppet_ai no disponible")
        try:
            resp = client.get("/catalog/finanzas",
                              headers={"Authorization": f"Bearer {tok}"})
            assert resp.status_code == 200
            tiers = {t["tier"] for t in resp.json()["templates"]}
            if ve_tecnico:
                assert "técnico" in tiers, f"{tier} debería ver técnico; vio {tiers}"
            else:
                assert "técnico" not in tiers, f"{tier} NO debería ver técnico"
        finally:
            self._borrar(uid)

    @pytest.mark.db
    def test_TS5_01_el_user_id_de_query_YA_NO_desbloquea_nada(self, client: TestClient):
        """REGRESIÓN T-S5-01 (el hallazgo del audit §0).

        Antes: `GET /catalog/finanzas?user_id=<uuid-de-un-tecnico>` devolvía el
        listado premium a CUALQUIERA — el tier se decidía con input del cliente.
        Ahora el parámetro no existe: se ignora, y sin sesión se ve lo de free.
        """
        try:
            tok, uid = self._sesion_con_tier("tecnico")
        except Exception:
            pytest.skip("Postgres puppet_ai no disponible")
        try:
            # el atacante conoce el uuid del técnico y NO tiene sesión
            resp = client.get(f"/catalog/finanzas?user_id={uid}")
            assert resp.status_code == 200
            tiers = {t["tier"] for t in resp.json()["templates"]}
            assert "técnico" not in tiers, (
                "el user_id de query string sigue desbloqueando templates premium")

            # y con la sesión de verdad, sí los ve (el gate no bloquea a todos)
            ok = client.get("/catalog/finanzas",
                            headers={"Authorization": f"Bearer {tok}"})
            assert "técnico" in {t["tier"] for t in ok.json()["templates"]}
        finally:
            self._borrar(uid)

    def test_catalog_sin_sesion_es_free(self, client: TestClient):
        """Sin Authorization → free (lo más restrictivo)."""
        resp = client.get("/catalog/finanzas")
        assert resp.status_code == 200
        for t in resp.json()["templates"]:
            assert t["tier"] != "técnico"

    @pytest.mark.db
    def test_token_basura_cae_a_free(self, client: TestClient):
        """Fail-closed: un token inválido no abre nada."""
        resp = client.get("/catalog/finanzas",
                          headers={"Authorization": "Bearer no-soy-una-sesion"})
        assert resp.status_code == 200
        for t in resp.json()["templates"]:
            assert t["tier"] != "técnico"


class TestCatalogDeclaresBeltPath:
    """B1 regression: the catalog DECLARES each template's belt_path (read from the
    real config.json). The UI must consume this verbatim — never derive it from the
    nicho name. Without it, demo-test (belt-demo, not belt-demo-test) is unsavable.
    """

    def test_every_template_exposes_belt_path(self, client: TestClient):
        resp = client.get("/catalog/finanzas")
        assert resp.status_code == 200
        for t in resp.json()["templates"]:
            assert "belt_path" in t, f"{t['id']} missing belt_path in API response"
            assert t["belt_path"], f"{t['id']} has empty belt_path"

    def test_belt_path_matches_real_config_json(self, client: TestClient):
        """The exposed belt_path must equal the belt_path in the template's own
        config.json on disk — proving the catalog declares it, not a convention."""
        import json

        resp = client.get("/catalog/finanzas")
        for t in resp.json()["templates"]:
            cfg_file = CATALOG_ROOT / "finanzas" / t["id"] / "config.json"
            cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
            assert t["belt_path"] == cfg["belt_path"], (
                f"{t['id']}: API belt_path {t['belt_path']!r} != "
                f"config.json belt_path {cfg['belt_path']!r}"
            )

    def test_demo_test_belt_path_breaks_the_convention(self, client: TestClient):
        """The whole point: demo-test's belt is belt-demo.mcp.json, NOT
        belt-demo-test.mcp.json. A convention `belt-{nicho}` would point at a
        non-existent file. The declared belt_path must point at the real file."""
        import json

        resp = client.get("/catalog/demo-test")
        assert resp.status_code == 200
        templates = resp.json()["templates"]
        assert templates, "demo-test must expose templates"
        for t in templates:
            cfg_file = CATALOG_ROOT / "demo-test" / t["id"] / "config.json"
            cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
            assert t["belt_path"] == cfg["belt_path"]
            # The naive convention belt-{nicho} would be belt-demo-test.mcp.json.
            assert "belt-demo-test" not in t["belt_path"], (
                "belt_path must reflect the declared belt-demo.mcp.json, "
                "not the belt-{nicho} convention"
            )
            assert "belt-demo.mcp.json" in t["belt_path"]
            # And the declared belt must actually exist on disk.
            from pathlib import Path
            assert Path(t["belt_path"]).exists(), (
                f"declared belt_path does not exist: {t['belt_path']}"
            )
