# VERIFICACIÓN (b) — EL GRAFO DE src/live/ Y QUÉ TOCA DINERO REAL
Medido sobre third_party/vibetrading @ 281c877 (importado, sha256 idéntico al origen).

## Los 5 caminos que pueden mover dinero, y su gate

| # | Camino | Entrada | Bifurcación | Gate en LIVE |
|---|---|---|---|---|
| 1 | **Orden por tool del agente** | `trading_place_order` / `trading_cancel_order` (tools del loop interno, NO del MCP) | `trading/service.py:place_order` | paper → `service.py:319` DIRECTO, sin gate · live → `service.py:334` `execute_live_order` |
| 2 | **Escrituras de eToro** (5 tools) | `etoro_close_position`, `etoro_cancel_close_order`, `etoro_edit_position_stops`, `etoro_copy_start`, `etoro_copy_close` | `trading/service.py:_route_sdk_write:377` | paper → `service.py:396` DIRECTO · live → `service.py:401` `execute_live_action` |
| 3 | **Broker remoto por MCP** (robinhood, ibkr) | tool remota WRITE/UNKNOWN | `live/registry.py:build_mcp_tool_wrappers` | SIEMPRE `LiveOrderGuardTool` (order_guard.py). UNKNOWN = WRITE (default-deny) |
| 4 | **LiveRunner autónomo** (por disparador/horario) | `POST /live/runner/start` | `live/runtime/runner.py` | NO coloca por sí mismo: **pinea el mandato en el prompt** y conduce un turno del agente → cae en los caminos 1/2/3, gateados. `runner.py:236` lo dice: «the gate and kill switch are hard backstops outside your control» |
| 5 | **Barrido de HALT** | `POST /live/halt` | `live/runtime/flatten.py`, `live_routes.py:561-573` | risk-reducing por definición (cancelar / cerrar). `flatten_on_halt` es opt-in por mandato; el default es CANCELAR SOLAMENTE |

## Conclusión

**No hay un 6º camino.** Todo llamador de `place_order` / `submit_order` fuera de estos cinco es
una definición (`def`), un mapa de clasificación, o código interno de un conector.

**Los dos gates son gemelos y comparten ceremonia** (`load_mandate` → expiry → `halt_flag_set` →
intención parseable → leer posiciones/balance REALES → `check_mandate`), los seis pasos fail-closed:
- `live/order_guard.py:830` líneas — para el carril MCP
- `live/sdk_order_gate.py:726` líneas — `execute_live_order` (órdenes) y `execute_live_action`
  (escrituras que no son órdenes)

## EL HECHO QUE GOBIERNA LA FASE 2

**`paper` NO pasa por el gate.** Es a propósito (es la sandbox del broker), y tiene una consecuencia
operativa dura para la vara:

> **Una orden de paper NO ejercita la máquina de mandato.** Verificar "paper trading end-to-end"
> NO verifica el gate. Son dos varas distintas y hay que correr las dos:
>   (i) el camino de paper — que coloca de verdad contra la sandbox
>   (ii) el gate — que sólo se ejercita con un perfil `live`, y por eso se prueba
>        **por sus negativas** (sin mandato → DENY; vencido → DENY; halt → DENY),
>        que es exactamente lo que se puede probar sin un centavo en juego.

## La barrera física de esta fase

Ningún perfil live puede colocar nada sin credenciales de broker en el entorno
(`module.build_config`). Medido en `/live/status` con entorno pelado: los 13 brokers con
`oauth_token_present: false`, `configured: null`, `mandate: null`. **Sin credenciales el camino 1-3
muere antes de tocar la red.**

## VERIFICACIÓN (a) — perfiles de usuario: NO son inyectables

`trading/profiles.py:27` `BUILTIN_PROFILES` es una tupla armada en tiempo de import desde los 13
módulos. `list_profiles()` devuelve sólo eso. `profile_by_id()` sólo busca ahí y **lanza ValueError**
ante un id desconocido. El único archivo de usuario, `~/.vibe-trading/trading-connections.json`,
guarda **el id seleccionado**, no perfiles.

**Probado con un archivo hostil** que declara un perfil `aleph-inyectado-live-trade` con
`readonly:false`, `environment:live`:
```
perfiles visibles: 43
hay alguno inyectado?: NINGUNO
selected_profile leído del archivo hostil: aleph-inyectado-live-trade
RECHAZADO con ValueError: unknown trading connector profile: aleph-inyectado-live-trade
```
**Deuda menor:** `load_selected_profile_id()` devuelve el string crudo sin validar; la validación
vive en `profile_by_id()`. Todo consumidor pasa por `profile_by_id`, así que no hay agujero — pero
un id arbitrario viaja un tramo antes de morir.

**¿Limpiables?** Sí, y de forma determinista: quitar los 8 perfiles live es borrar 8 literales
`TradingProfile` en 8 archivos, con archivo:línea ya censados en el estudio §7.1. No hace falta
tocar `src/live/`.
