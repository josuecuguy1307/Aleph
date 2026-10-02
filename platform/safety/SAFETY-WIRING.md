# T9-safety — handoff de cableado para el integrador

La capa de safety vive **entera y aislada** en `platform/safety/` (zero conflicto). Para que
los guards estén **en el path** (no solo disponibles), toqué 5 archivos fuera de mi área con
ediciones **mínimas, aditivas y fail-open-on-import**. Todas marcadas con `# [T9-safety]`.

> Patrón de cada seam: `try: from safety… import …` → guard → `except ImportError: pass`.
> Si la capa de safety no está, **el core sigue corriendo** (no rompo nada). El guard solo
> puede **rechazar/frenar**; nunca afloja. Mergear estas 5 ediciones deliberadamente.

## Ediciones fuera de mi área

| Archivo | Owner | Qué agregué (`# [T9-safety]`) |
|---|---|---|
| `platform/inspection/bridge.py` | T4 (motor) | `run_recon_to_space`: 2 kwargs nuevos (`subject`, `allow_local_fixture`) + guard `guard_recon(target_url)` ANTES de levantar browser. Si frena, emite el rechazo al space y corta. |
| `platform/inspection/demo_live.py` | T4 (motor) | la llamada del fixture benigno pasa `allow_local_fixture=True` (loopback confiable). |
| `platform/inspection/observe/replay.py` | T4 (motor) | `SynthesizedTool.call`: kwarg `subject` + guard `guard_replay(url, is_write)` ANTES del `urlopen`. Devuelve `{refused, by:"safety"}` si frena. Encima del gate `allow_write` del core. |
| `product/backend/app/phase1/inspect_router.py` | T4 (`/v1/inspect`) | gate de borde: rate-limit por `space_id` + `url_guard.is_safe(target_url)` si llega un target real → `429`/`400`. Bootstrap de `sys.path` para importar `safety`. |
| `product/backend/app/phase1/executor.py` | Backend/T5 | `run_puppet_e2e`: `legal_precheck(recipe)` al inicio del `try`. Si `allow=False` (ej. medicina en prod) **corta el run** sin crear fila; siempre expone `out["legal"]`. |

## Por qué cada una es segura de mergear

- **No cambian la firma de retorno** de ninguna función core (solo agregan campos: `out["legal"]`,
  `{refused, by}`). Los kwargs nuevos tienen default seguro → callers existentes no se enteran.
- **bridge/demo_live**: el fixture sigue corriendo (loopback permitido explícito); un target
  externo malicioso se bloquea. El demo `python platform/inspection/demo_live.py` no cambia.
- **replay**: el gate `allow_write` del core sigue intacto; safety es una segunda llave.
- **inspect_router**: hoy `target_url` es reservado (no usado) → el guard es defense-in-depth
  para cuando T4 prenda el path headed. El rate-limit aplica ya.
- **executor**: el enforcer de gates (money/send → `confirma-siempre`) **no se toca**; legal
  agrega lo que el enforcer no hace (bloqueo por entorno + aviso por nicho).

## Si hay conflicto de merge

T4 avanzó `inspect_router.py`/`bridge.py`/`replay.py` en su worktree (`18d5ba3`). Si chocan:
1. Tomá la versión de T4 como base.
2. Re-aplicá **solo** los bloques `# [T9-safety]` de esta rama (son autocontenidos).
3. Corré `python platform/safety/verify_done_bar.py` — si da TODO VERDE, el cableado quedó.

## Orden de dependencia sugerido

`platform/safety/` no depende de nadie → puede mergear **primero**. Los 5 seams dependen de que
`platform/safety/` exista; si entran antes, el `except ImportError` los deja inertes (sin romper).
