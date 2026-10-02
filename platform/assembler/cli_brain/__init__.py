"""cli_brain — BYO-CLI: el CLI local del usuario (Claude Code / Codex / Grok) como CEREBRO.

Patrón 3 · brain-as-provider: un wrapper DELGADO spawnea el CLI YA AUTENTICADO del
usuario como puro completion in/out (tools del CLI OFF). El Núcleo de Aleph conserva
el loop, el belt, los gates y el Eco. El CLI solo piensa.

- Interface única: CliBrainProvider (base.py). Implementaciones en *_cli.py.
  Un CLI nuevo entra como 1 clase + 1 `CliSpec` en registry.py — no se copia la
  lista de ids en el producto.
- Aleph JAMÁS ve/guarda/toca tokens de la suscripción: la única interacción con el
  auth es preguntar el estado (`claude auth status` / `codex login status`).
- model_final = el modelo REAL que el CLI reportó (anti-grift de autenticidad).
- Rate-limit de la ventana de suscripción → clasificado + narrable (D4), jamás
  false green ni muerte silenciosa.
"""
from .base import BrainResult, BrainStatus, CliBrainProvider, assert_argv_safe  # noqa: F401
from .claude_cli import ClaudeCliProvider  # noqa: F401
from .codex_cli import CodexCliProvider  # noqa: F401
from .grok_cli import GrokCliProvider  # noqa: F401
from .detect import PROVIDERS, detect_all, get_provider  # noqa: F401
from . import registry  # noqa: F401
