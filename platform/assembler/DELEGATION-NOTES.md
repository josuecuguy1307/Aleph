# Agente anidado — el BRANCH REAL de delegación (paso 2)

> Paso 1 (`contrato-agentes`): el contrato acepta `belt.agent_refs[]`, el validador lo
> valida, `belt_resolver.resolve_agent_refs()` devuelve `ResolvedAgent{type:'agent', recipe}`.
> Spike (`delegacion-spike`): los 5 rieles PROBADOS bajo ataque con cerebro STUB.
> **Este paso** lleva los rieles al motor VIVO (`recipe_assembler.assemble_and_run`).

## Qué es

Cuando el cerebro del **padre** invoca un `agent_ref` (de `belt.agent_refs[]`), el motor —
en el punto de ejecución de tool de `assemble_and_run` — **DELEGA** en vez de `registry.call`:
corre el **sub-agente** con su PROPIO loop (`assemble_and_run` de la receta hija) y el padre
consume el resultado como el retorno de esa "tool". El sub-agente se expone al cerebro del
padre como una capacidad invocable (`fn`) cuyo nombre/descr salen de la **meta** de la receta hija.

Archivos:
- `delegation.py` — el branch + los 5 rieles + las 4 decisiones (orquesta; no corre el loop).
- `recipe_assembler.py` — wiring ADITIVO: kwargs internos de recursión + el branch en el loop.
- `deleg_fixtures/` — fixtures + `verify_delegation_real.py` (la evidencia).

## Los 5 rieles (REALES sobre el motor vivo)

1. **GATE POR HIJO** — cada sub-run construye `build_enforced_gate` sobre la receta DEL HIJO;
   el `approve` del padre **NUNCA** se reenvía (`approve=None`). Un hijo malicioso (gates=off,
   manda correo) cae a `needs_ok` **aunque el padre apruebe todo**.
2. **DEPTH + CICLO por PATH CANÓNICO** — corte en `MAX_DEPTH=3`; la huella de ciclo es el
   **path canónico resuelto** de la receta (mejora sobre el spike, que colapsaba por nombre+belt:
   dos agentes distintos con el mismo `meta.name` ya no se confunden; un self-ref / A→B→A sí se corta).
3. **DEADLINE PROPAGADO** — el sub-run HEREDA el deadline ABSOLUTO del padre (`_deadline_abs`),
   no recalcula `max(5, deadline_s)` por nivel. La cadena entera comparte el presupuesto del top.
4. **WORKDIR AISLADO** — cada sub-run en `parent/sub-<turn>-<idx>-<slug>/`; nunca el compartido.
5. **PUENTE / FRONTERA** — sólo el RESULTADO del hijo (string `{sub_agente,ok,resultado,truncado,error}`)
   cruza al cerebro del padre (`messages`); sus pasos internos quedan en `record["sub_runs"]` (LOG).

## Las 4 decisiones de diseño

6. **MODELO DEL HIJO** — default **HEREDA** el del padre; con flag `belt.agent_policy.child_model:"own"`
   (o env `PUPPET_CHILD_MODEL=own`) y si la hija declara `model` propio, usa el suyo.
7. **BYOK HÍBRIDO** — el hijo recibe SÓLO las keys de los servicios que SU receta declara
   (`scoped_byok_resolver`); un intento de leer un `byok_ref` no declarado → `""` (negado).
8. **GUARDRAILS DEL PADRE (techo, no llave)** — el padre puede RESTRINGIR clases de acción del
   hijo (`belt.agent_policy.child_guardrails: {deny_classes|deny_servers|deny_tools}`):
   `ChildCeilingGate` baja `EXECUTE→BLOCKED`. **Sólo restringe**: nunca convierte un `needs_ok`/
   `blocked` en `execute`, y como `approve` no se reenvía (riel 1) tampoco pre-autoriza lo gated.
   El techo es **TRANSITIVO** (`merge_ceilings`): se endurece monótono hacia abajo — un nieto no
   evade el techo del abuelo metiendo una capa media benigna.
9. **PARALELO** — varias delegaciones en un mismo turno corren CONCURRENTES (un hilo por hijo);
   cada uno su workdir/gate/deadline-restante. Sin estado mutable compartido: cada hilo devuelve su
   tupla y el padre splicea single-thread tras el join.

## Regresión

Una receta SIN `agent_refs` corre **byte-idéntica** a hoy: `build_agent_tools` devuelve `([], {})`,
la partición deja `_tool_calls_only = _calls` (mismo objeto), el branch de delegación se saltea, y
los kwargs internos (`_depth=0`, `_deadline_abs=None`, …) reproducen el comportamiento previo.

## Correr la evidencia

```bash
cd platform/assembler/deleg_fixtures
# ataques + decisiones + regresión (headless, determinista, cero tokens — stubea SÓLO el cerebro):
python3 verify_delegation_real.py
# + caso feliz E2E con cerebro REAL (shim Opus :8923, tool_calls>0):
PUPPET_BRAIN_SHIM=1 PUPPET_BRAIN_SHIM_MODEL=claude-code-opus-4.8 python3 verify_delegation_real.py --happy
```

Los ATAQUES stubean SÓLO el cerebro (FakeBrain monkeypatchea `_route_chat` con un guión de
tool_calls indexado por mensajes-assistant del propio run → no se contamina entre runs); las
TOOLS son un MCP server REAL (`deleg_server.py`) y el gate/deadline/workdir/bridge son el código
REAL del motor. El CASO FELIZ corre con Opus real: el padre delega → el hijo ejecuta `add(21,21)`
de verdad → **42** cruza limpio al padre.
