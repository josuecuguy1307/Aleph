# Security Gates — implementación de la matriz §4 del threat-model (misión 0014)

> Squad **Security** (Engineering) · 2026-06-11 · primera misión del squad en la historia.
> Pareja de implementación del threat-model: **Trust diseñó (P010, vinculante Fase 13), Security construyó.**
> **El diseño vive en `platform/gates/THREAT-MODEL.md`** — vectores de ataque + reglas
> transversales, rescatados del P010 original al extraer Puppet del repo.
> Clase ledger: **engineering / PARAMETRIZABLE** — la matriz entra como CONFIG (`matrix.example.json`);
> los niveles NO están hardcodeados por template. Cambiar de nicho = cambiar el JSON, no el motor.

---

## POSICIÓN

**Recomendación única:** adoptar estas 4 piezas como la capa de seguridad del runtime de agentes
de usuario y **destrabar la exposición de templates money-touching en el workshop v0**. La matriz §4
queda implementada tal cual (VINCULANTE, Fase 13): ningún template money-touching corre sin su gate,
y la regla dura de Tool-belt (canal DESPUÉS del gate) ya tiene su gate de envío construido y probado.

**3 números:**
1. **42/42 tests adversariales PASS** (criterios a–e del done + E2E T05), cada uno con su **par M002**
   (rechazo + control positivo) → no es reject-all/scrub-all/block-all: lo seguro avanza, lo legítimo pasa.
2. **0 apariciones** de la key del usuario en el grep sobre TODO lo que ve el modelo + los logs del runtime
   (criterio c) — el vault entrega el valor SOLO al `env` del subprocess MCP.
3. **E2E real contra el assembler** (`MCPServer` + `ToolRegistry` reales, fixture con la superficie de T05):
   `batch_update_cells` sin OK **NO escribe**; con OK **SÍ escribe**; a un `spreadsheet_id` ≠ el atado **BLOQUEA**.

**Confianza: ALTA** en la mecánica (el gate intercepta en el único cuello — `ToolRegistry.call` — y el
E2E lo prueba contra el assembler real). **MEDIA** en la cobertura de patrones de secreto del scrubber:
es una red de seguridad regex, no una garantía formal; el control real de la key es el vault (no la ve el modelo).

**Qué cambiaría la conclusión:**
- Si Tool-belt cableara un canal de envío (Email/WhatsApp) **antes** de montar el gate de envío → se rompe
  la regla dura Fase 13. El gate ya existe; la condición es que el canal lo use, no lo saltee.
- Si el runtime de producción ejecutara código en un kernel que **sí** herede el `env` del runtime (no
  `clean_env`) o un cwd no acotado → el sandbox de admisión (`guard_code`) seguiría filtrando, pero se
  perdería la defensa en profundidad. La config de spawn del kernel debe usar `SandboxGuard.clean_env`.
- Si apareciera un patrón de secreto nuevo (key con forma no cubierta) → ampliar `SECRET_PATTERNS`; el
  vault no se ve afectado (sigue siendo el control primario).

---

## Las 4 piezas

| # | Pieza | Archivo | Qué hace | Punto de integración |
|---|---|---|---|---|
| 1 | **Gate de aprobación + vista previa** | `approval_gate.py` | Ante acción sensible (según la matriz) PAUSA y produce el payload qué/dónde/preview/OK con el copy oficial §2. Lista blanca de uno (destino atado al crear). | `ToolRegistry.call` (vía `GatedRegistry`) |
| 2 | **Vault de credenciales** | `vault.py` | Keys cifradas con Fernet; se inyectan SOLO al `env` del subprocess MCP. Nunca al contexto del modelo ni a logs (`redacted_env_log`). | spawn de MCP servers |
| 3 | **Sandbox de ejecución** | `sandbox.py` | `guard_code` rechaza código que lee `~/.ssh`/`.env`/vault o abre red/shell; `clean_env` arranca el kernel sin secretos; workdir acotado. | tools de código (T02/T04/T08) |
| 4 | **Scrubber de salida** | `scrubber.py` | Filtra secretos + payloads de fórmula en la salida a canales. **Coordina con `platform/sanitizer/` (misión 0013) sin duplicar.** | resultado de tool → modelo, y salida → usuario/canal |

**Cableado:** `runtime_integration.py` → `make_gated_registry(ToolRegistry)` envuelve el registry del
assembler **sin tocar `assembler.py`** (aditivo, reversible). Config de la matriz: `matrix.example.json`.

### Niveles de la matriz (config, copy §2 oficial)

| Nivel interno | Copy oficial (workshop) | requiere OK |
|---|---|---|
| `auto-ejecuta` | "Tu agente lo hace solo." | no |
| `confirma-una-vez` | "Tu agente te avisa la primera vez y después sigue solo." | sí (1ª vez) |
| `confirma-siempre` | "Tu agente te pregunta cada vez, antes de hacerlo." | sí (cada vez) |
| `prohibido-en-tier-average` | "Tu cuenta básica no puede hacer esto." | bloqueado |

### Contrato de UX del gate (Fase 13 — el workshop lo refleja SIEMPRE)

El payload de `NEEDS_OK` trae las 4 partes, sin jerga:
`que_va_a_hacer` (a) · `donde_afecta` (b) · `vista_previa` (c) · `requiere_ok`+`boton_ok` (d) · `leyenda` (copy §2).

---

## Coordinación con el sanitizer (misión 0013) — sin duplicar

**División de trabajo (P010 §B1):**
- `platform/sanitizer/` → **escritura a ARCHIVOS** (.xlsx/.csv): neutraliza la fórmula en el archivo entregado.
- `platform/gates/scrubber.py` → **salida a CANALES** (mensaje al usuario, Email, WhatsApp): neutraliza el
  payload de fórmula en el TEXTO del mensaje.

El scrubber **delega** la neutralización de fórmula en el sanitizer **si el módulo existe** (busca
`platform/sanitizer/sanitizer.py` y reutiliza su `neutralize_formula`); si todavía no existe (hoy:
0013 en `processing`), usa un fallback local equivalente. **Cero re-implementación de la regla del prefijado.**

---

## Cómo correr los tests

```
python3 platform/gates/tests_gates.py     # 42 PASS · 0 FAIL — done a-e + E2E T05
```

El Reviewer security RE-CORRE este comando. Cada criterio trae su par M002 (rechazo + control positivo).

---

## ## PUNTOS CLAVE (founder-facing)

- **El candado del nicho #1 está puesto y probado: 42/42 tests verdes.** Tu agente de finanzas YA puede
  tocar tu Google Sheet en vivo, correr código y (en el futuro) mandar por WhatsApp — pero **nunca sin
  preguntarte primero, mostrándote en español qué va a hacer, dónde, una vista previa y un botón de OK.**
- **Seguro pero no paralizado (tu principio rector, tal cual):** no prohibimos ninguna capacidad — la
  envolvemos. La prueba: con tu OK, la escritura en el Sheet **sí** ocurre (no es un "no" a todo).
- **Tu clave nunca la ve el modelo.** Grep en todo lo que el modelo lee + todos los logs = **0 apariciones**.
  La key vive cifrada y solo la usa la herramienta por debajo, jamás el cerebro del agente.
- **Un cuaderno malicioso que intente robar tus llaves SSH o tu vault se frena con un mensaje claro**, no con
  un stack trace. Y el código legítimo de un backtest pasa sin fricción.
- **Lo que faltaba para abrir el workshop con templates que tocan plata, ya no falta.** Tool-belt puede
  cablear Email/WhatsApp **ahora que el gate de envío existe** (regla dura: el canal va DESPUÉS del gate).

**Decisión que NO se te pide** (autoridad COMMAND Fase 15): la implementación de gates money-touching es
R4 — reservada, pero esta misión **construye** la matriz que vos ya aprobaste como vinculante (Fase 13),
no la re-decide. Si querés redirigir algo de la mecánica, es visible acá.

---

## entregar_a

- **Frontend (workshop v0, misión 0009):** consumí `approval_gate` para renderizar el gate de cada template.
  El payload de `NEEDS_OK` ya trae las 4 partes del contrato de UX + el copy §2 en `leyenda`. La galería
  muestra el nivel de cada template; el botón de OK del workshop es el `approval_callback`.
- **Tool-belt Engineering:** **el gate de envío (confirma-siempre + vista previa) YA existe y está probado.**
  Habilitado para cablear Email/WhatsApp — el canal usa el gate, no lo saltea (regla dura Fase 13). El vault
  (`vault.py`) es donde viven las keys gratis AV/FRED y el OAuth Google que conectás just-in-time.
- **Trust & Delegation:** la matriz §4 quedó implementada tal cual la diseñaste (P010). El gate de "lista
  blanca de uno" (atar el agente al `spreadsheet_id` declarado, B2) está construido y verificado en el E2E.
  El overlay de credencial (no al contexto) y el de código (sandbox) materializan tus overlays transversales.

> **Pendiente que NO bloquea esto:** cuando 0013 (sanitizer) cierre y cree `platform/sanitizer/sanitizer.py`
> con `neutralize_formula`, el scrubber lo detecta y reutiliza automáticamente — sin tocar este código.
