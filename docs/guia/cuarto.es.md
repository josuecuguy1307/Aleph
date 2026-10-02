# El Cuarto {#cuarto}

El Cuarto es el taller donde armas tu agente. Es una escena viva (un diorama):
cada cosa que le agregas aparece como una pieza, y cuando guardas, el agente
cobra vida. Acá se decide **qué** es el agente; en La Sala se lo **usa**.

## El Núcleo — el agente {#nucleo}

El Núcleo es el agente en sí: su **modelo** (lo que piensa), su **identidad** y su
**objetivo**. Es quien decide qué pieza usar en cada momento y **re-decide con
cada eco** (cada resultado que vuelve del mundo). No es un guion fijo: razona,
elige herramienta, mira lo que pasó y vuelve a elegir.

- **Identidad y objetivo** son texto que le das ("Eres un asistente claro y
  confiable…", "analista de finanzas…", "asistente de oficina…"). Definen su
  tono y sus reglas de trabajo.
- El **modelo activo se confirma al correr**: si degrada a un modelo de
  respaldo, la Sala lo muestra. La verdad del modelo sale de la ejecución, no
  de "el binario existe". (Ver `cerebros.es.md`.)

## El Núcleo reparte — workers y plan del run {#workers}

Cuando el Núcleo declara un **plan**, ese plan aparece en el panel del run: los
pasos en orden y, en cada uno, si va a **repartirse**. Un paso marcado para
repartir muestra cuántos **workers** abre.

Los workers son ayudantes **efímeros**: el Núcleo los abre para un tramo pesado
—leer, extraer, contar sobre varias fuentes— y se cierran cuando ese tramo
termina. Aparecen en el panel de workers y **sólo ahí**; no son piezas de tu
agente ni quedan guardados. Si no hay ninguno activo, es que no hay nada
repartido en este momento.

Tu plan de cuenta fija cuántos pueden correr **a la vez**; el resto va en fila.

## Las zonas y la puerta MCP {#zonas}

La escena se organiza en zonas: el **Núcleo** (el agente), la **Conexión**
(puertas a apps del mundo), el **Contexto** (lo que el agente sabe). La **puerta
MCP** es por donde entran las herramientas de una app: al conectarla —con OAuth
o con una llave— sus tools reales caen en la escena como piezas equipables.

## La Lente de flujo {#lente}

La Lente de flujo es una **vista derivada** del armado: te muestra el orden en
que las piezas se activarían. **No toca el armado** — solo lo dibuja de otra
forma. Apagarla o encenderla no cambia nada de lo que construiste.

## La forma de sesión {#sesion}

Cada software declara **cómo se entra**: abierto (sin credencial) · token ·
login (usuario y contraseña) · navegador con OAuth y 2FA. Cuando hay 2FA, **el
segundo factor lo pones tú** — el motor nunca resuelve un 2FA por su cuenta.
(Ver `conectar.es.md`.)

## La evidencia (modo dev) {#evidencia}

El modo dev muestra la **evidencia técnica cruda** de cada paso del Motor B: el
request real, la respuesta real, el MCP crudo. Está oculto por defecto porque lo
importante —la verificación contra el entorno real— ya está a la vista. Lo
enciendes solo cuando quieres auditar el detalle.

## El Guía en el Cuarto {#guia}

El Guía es un copiloto de manos: puede mirar y mover el Cuarto, abrir closets,
señalar piezas y **abrir flujos** por ti. Tiene una línea que **nunca cruza**:
**propone y abre, nunca completa** la acción que sale al mundo. Para actuar sobre
el mundo real —enviar, pagar, ejecutar— el trabajo pasa a La Sala, donde tú das
el OK. Si le pides algo fuera de su alcance, te lo dice en vez de fingir que lo
hizo. (Ver `cerebros.es.md` para su modelo y sus límites.)

## Las piezas todavía de solo lectura {#solo-lectura}

Chat, Opciones y Código de una pieza llegan en una fase próxima. Hoy la pieza es
de solo lectura: puedes verla, no editarla desde ahí. (Ver `piezas.es.md`.)

## Mis agentes — lo que guardaste {#mis-agentes}

"Mis agentes" es la lista de los agentes que guardaste en tu cuenta. Abres uno y
sigues donde lo dejaste: vuelve el armado completo, con cada pieza en su lugar.
Si todavía no guardaste ninguno, la lista está vacía — arma uno en el Cuarto y
toca **⤓ Guardar**.

## Por dónde se empieza {#empezar}

El Cuarto arranca con el Núcleo solo. Desde ahí hay tres caminos, todos en el
menú **⋯** de la barra:

- **＋ Equipar** — sumar piezas del catálogo (lo más rápido para empezar).
- **⌕ Inspeccionar** — traer un software que todavía no está en el catálogo: se
  inspecciona y sus herramientas reales caen en la escena.
- **💬 Guía** — si prefieres contarlo con tus palabras y que el Guía lo arme.

Cuando ya hay piezas, el botón **▶ RUN** las pone a trabajar.

