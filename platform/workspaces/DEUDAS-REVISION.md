# Deudas de Revisión — packs de workspace

Deudas **anotadas y no construidas**, con su evidencia medida. Van acá y no en un acta del
escritorio porque lo que no está en el árbol no existe: quien toque `pack.py` o el registro de
`_WORKSPACE_STACKS` tiene que tropezarse con esto.

> Nota de procedencia: no encontré un archivo canónico de deudas de Revisión en el árbol ni en
> el escritorio (busqué secciones «Revisión» con seguridad/limpieza; `04-CONECTORES-CENSO-Y-PLAN.md`
> no existe en disco). Este archivo se crea acá por eso. Si existe una lista canónica, esta
> entrada se mueve tal cual — está escrita en la forma que pidió el dueño.

---

## LEY 12 · Diseño está fuera de las dos exclusividades, y un click le mueve el cerebro

**Estado: VIVO HOY, no latente.** Medido 2026-08-17 sobre `main f51385e8`.

**Qué es.** Los cuatro importadores de Diseño —`config:v1:import-codex-config`,
`import-claude-code-config`, `import-gemini-config`, `import-opencode-config`
(`third_party/codesign/apps/desktop/src/main/onboarding/register.ts:213-266`, expuestos al
renderer por `preload/index.ts:608-614`)— **escriben** un proveedor de modelo con su key y
mueven el proveedor activo al importado:

    onboarding/external-imports.ts  →  writeConfig(...)
                                       activeProvider: imported.provider.id   (:167, :210)

Y la fila de `diseno` en `_WORKSPACE_STACKS` **no declara** `engine`, ni `brain_exclusivo`, ni
`brain_lectura`. Medido: las dos exclusividades piden justamente eso —
`exclusividad_del_cerebro` corre si `engine == "opencode"`, `exclusividad_por_terna` si
`brain_lectura == "settings_llm"`— así que **ninguna de las dos corre sobre Diseño**.

⇒ Un click del usuario en cualquiera de esos cuatro botones le saca el cerebro a Aleph, y la
casa no lo detecta, no lo repara y no lo dice.

**Es de MODELOS, no de conectores.** Es el mismo defecto que Finanzas cerró con su obra C: el
stack tiene su propia superficie para elegir cerebro y la presencia del nuestro no prueba
exclusividad. Por eso no entró en F1-conectores, que es sobre credenciales.

**Por dónde va el arreglo.**

1. **Por el puntero, no editando el árbol importado.** `aleph-pack.json` es el único canal de
   la casa hacia este motor (ver `config_format == "launcher"` en `pack.py`), y su lanzador
   traduce. Declarar `brain_exclusivo` a secas NO sirve: escribiría la lista blanca en el
   `config.toml` que este pack no usa — el defecto del archivo muerto que ya se pagó una vez y
   que está documentado ahí mismo («un mecanismo que se ve adoptado y no hace nada es peor que
   uno que falta»).
2. **El mecanismo ya existe: es enchufar, no escribir.** `exclusividad_del_cerebro`
   (`pack.py`) ya hace detectar → apagar → releer → reportar, con su vocabulario
   (`intrusos` / `apagados` / `sin_apagar`) y su copy ya probado en Oficina. Lo que falta es la
   vía de lectura y de apagado para este motor, declarada en la fila como se declaró
   `brain_lectura` para el tercero.
3. **Verificar exige la TERNA completa, no el id.** Está medido en el árbol y el comentario lo
   dice: el desvío mantuvo `provider = openai` y cambió `model_name` y `base_url`; comparar
   sólo el id habría dado verde con el turno saliendo por la puerta de al lado. Acá el análogo
   es `activeProvider` + `activeModel` + el `baseUrl` del bloque del proveedor.
4. **Releer, no creerle al 200.** Y su recíproca, que costó una medición en F1: un no-200
   tampoco prueba que no cambió. Se relee el estado, siempre.
5. **Copy de Oficina: detectado, reparado, anunciado.** Y si no se puede apagar, «detectado y
   anunciado, no reparado», que es lo que ya se hace con Legal. Ninguna causa llega a una
   superficie sin copy.

**`[no medible]` sin correr Electron:** si la pantalla llega a mostrar esos cuatro botones bajo
el pack. El censo los había contado como «no expuestos»; medido acá, los handlers existen, están
registrados y el preload los expone — lo que no se midió es la cara.
