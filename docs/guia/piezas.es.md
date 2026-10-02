# Piezas — armar el agente {#piezas}

Cada cosa que le das al agente es una **pieza** en el Cuarto. Las piezas se
guardan en **closets** (armarios): chiquitos, pegados a la pieza, anidados y
progresivos. El primer nivel muestra lo mínimo —qué es, su estado, una acción— y
"más" expande. Nunca se vuelca todo plano.

## Tipos de pieza {#tipos}

- **Puerta (conector):** una puerta a una app. Al conectarla —OAuth o llave— caen
  sus tools reales en la escena.
- **Tool:** lo que el agente hace. Puede leer del mundo, sacar al mundo o
  procesar.
- **Gate (candado de permiso):** frena y pide tu OK antes de tocar afuera. Eso
  **no se puede auto-aprobar** con ningún ajuste.
- **Contexto / conocimiento:** skills, recetas, memoria y bitácora del agente.

El chat, las perillas y el código de una pieza **escriben lo mismo**: son tres
formas de tocar la misma configuración.

## Elegir el equipo {#equipo}

Cuéntale arriba, en tus palabras, qué quieres que haga. Mientras escribes, se
iluminan los closets que le sirven. Fíjate en los marcados "te sirve" o abre
cualquiera y explora. Tu agente también puede **coordinar ayudantes**
especializados: suma los que necesite.

## Qué dice el estado de una pieza {#estado}

Tocá una pieza y sus acciones se abren **en arco a su alrededor**. Al pie del arco
hay una línea que dice cómo está esa pieza. Son cinco estados y nada más:

- 🟢 **Probado** — corrió de verdad contra el servidor y funcionó. Dice cuándo.
- 🟡 **Sin probar** — está puesta, pero nadie la probó todavía. Tocá **Probar**.
- 🔴 **Roto** — se probó y falló. Al lado va la causa: falta tu llave, tu
  conexión está caída, el proveedor devolvió error… La causa dice **de quién es la
  culpa**, así no vas a revisar tu WiFi cuando el problema es una llave.
- ⚪ **Sin configurar** — le falta la cuenta o la llave para poder probarse.
- 🔒 **Premium** — tu plan no la cubre.

**Probar** y **Probar de nuevo** son el mismo botón: cuando la pieza está en rojo
cambia de nombre, para que se lea que es un reintento. Nunca vas a encontrar dos
botones distintos para lo mismo.

Si el reintento vuelve a fallar, el arco deja de ofrecerte repetir y te abre **el
camino**: los pasos concretos para arreglar esa pieza. Un botón que te deja igual
dos veces no existe en el Cuarto.

El error crudo del servidor **siempre** está disponible, plegado bajo la línea de
estado. No lo escondemos ni lo resumimos: la causa te dice qué clase de falla es,
el crudo te dice qué contestó la máquina.

## El candado y los permisos {#candado}

Todavía nada que salga al mundo está activo. Si sumas correo o mensajes, van a
aparecer en la lista de permisos — y **siempre** te van a preguntar antes.

El candado se dibuja **sobre el cable** que va de la pieza al Núcleo: uno por
pieza, pegado al cable, en el punto por donde pasa lo que esa pieza hace. Ahí es
donde frena.

Sólo aparece en las piezas que **tocan afuera** — mandar, pagar, publicar,
escribir. Una pieza que sólo lee (imágenes médicas, papers, catálogos públicos) no
lleva candado, y tampoco se te ofrece ponerle uno: no hay nada que frenar.

Tocalo y te dice las cuatro cosas que hacen falta para decidir: **qué frena**, con
qué **regla** (siempre · una vez · quitar), **cuántas veces** frenó ya, y por
dónde ver las decisiones que tomaste.

**Quitar el candado no es barra libre.** Aunque lo saques, el motor sigue
reteniendo lo que mueve **plata** y lo que **envía** cosas a otras personas. Ese
piso no se baja con ningún ajuste.

## El plan, antes de darle vida {#plan}

Antes de guardar, mira el plan: son los **pasos en orden**, qué armario usa cada
uno y dónde frena para pedirte el OK. Tú lo apruebas y solo entonces arranca.
Mientras corre, va tildando pasos y **frena solo donde algo sale al mundo**. Al
terminar, lo que salía al mundo pasó por tu OK.

## Revisar antes de equipar {#revisar}

Cuando inspeccionas un software, antes de equipar nada te mostramos **lo que va a
saber hacer**: la lista de herramientas reales que se leyeron del servidor, con
una casilla cada una y **todas marcadas**. Tocas **Continuar** y se equipa
exactamente eso. Destildar es opcional: lo que destildes no entra.

Son las herramientas **reales que el Motor B leyó del servidor** — cero
placeholders. Lo que destildes no entra al MCP que se sella; el resto se equipa
tal cual. El panel muestra de qué servidor salieron.

No hay modo que encender — la lista aparece sola, siempre. El detalle crudo de la
forja (qué se propuso, qué validó el motor) vive en la evidencia `</>`.

## Todavía de solo lectura {#solo-lectura}

Chat, Opciones y Código de una pieza llegan en la próxima fase; hoy la pieza es
de solo lectura. (Ver `cuarto.es.md`.)
