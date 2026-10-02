#!/usr/bin/env python3
"""Structural witness for the Gate 4 DeepTutor amputations."""

from __future__ import annotations

from pathlib import Path

import sys


ROOT = Path(__file__).resolve().parents[1] / "third_party" / "deeptutor"
PACKAGE = ROOT / "deeptutor"
sys.path.insert(0, str(ROOT))


def must_not_exist(relative: str) -> None:
    assert not (PACKAGE / relative).exists(), f"amputated organ remains: {relative}"


def main() -> None:
    for path in (
        "partners",
        "services/partners",
        "services/cli_apps",
        "services/codex_auth",
        "multi_user",
        "services/auth.py",
        "services/pocketbase_client.py",
        "api/routers/auth.py",
        "api/routers/partners.py",
        "api/routers/space_cli_apps.py",
        "services/parsing/engines/pymupdf4llm",
        "services/llm/provider_core/openai_codex_provider.py",
    ):
        must_not_exist(path)

    for path in (
        "compose.codex-oauth.yaml",
        "compose.yaml",
        "docker-compose.dev.yml",
        "scripts/docker_compose.py",
        "scripts/pb_setup.py",
    ):
        assert not (ROOT / path).exists(), f"amputated deployment path remains: {path}"

    registry = (PACKAGE / "services/provider_registry.py").read_text(encoding="utf-8")
    assert 'PROVIDERS = (ProviderSpec(name="custom"' in registry
    assert "openrouter" not in registry and "openai_codex" not in registry

    main_source = (PACKAGE / "api/main.py").read_text(encoding="utf-8")
    assert "allow_origin_regex" not in main_source
    assert "from deeptutor.services.partners" not in main_source
    assert "from deeptutor.services.pocketbase_client" not in main_source

    runtime_settings = (PACKAGE / "services/config/runtime_settings.py").read_text(
        encoding="utf-8"
    )
    assert "POCKETBASE_" not in runtime_settings
    assert '"pocketbase_url"' not in runtime_settings

    dependencies = (ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()
    for forbidden in (
        "pymupdf",
        "pymupdf4llm",
        "pocketbase",
        "oauth-cli-kit",
        "anthropic>=",
        "dashscope>=",
        "perplexityai>=",
        "deeptutor[partners]",
    ):
        assert forbidden not in dependencies, f"forbidden dependency remains: {forbidden}"
    assert "pypdfium2>=5.12.1" in dependencies

    from deeptutor.services.config.provider_runtime import resolve_llm_runtime_config

    resolved = resolve_llm_runtime_config(
        {
            "services": {
                "llm": {
                    "active_profile_id": "aleph",
                    "active_model_id": "brain",
                    "profiles": [
                        {
                            "id": "aleph",
                            "binding": "custom",
                            "base_url": "https://border.invalid/v1",
                            "api_key": "",
                            "models": [{"id": "brain", "model": "aleph/brain"}],
                        }
                    ],
                }
            }
        }
    )
    assert resolved.binding == "custom" and resolved.provider_name == "custom"
    print("PASS extirpations: identity/partners/Codex/CLI-Anything/PyMuPDF absent; custom border only")


if __name__ == "__main__":
    main()
