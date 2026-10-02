# Modelos — la cognición {#cerebros}

El modelo es lo que razona por tu agente. La cognición es **prestada** y
cambia cada mes; lo que importa —y lo que es tuyo— es el entorno: tus datos, tus
herramientas, tus reglas. Incluso tu propia key, si quieres.

## De dónde sale el modelo {#origen}

- **Ruta incluida (hosted de Aleph):** disponible sin configurar. La lane
  incluida no siempre expone una señal de salud en el runtime; **se confirma al
  ejecutar**.
- **Tu propia API (BYOK):** este modelo usa tu propio acceso. Pegas tu key y
  queda listo — no la pedimos antes de que elijas. La llave se guarda cifrada.
- **Tu CLI por suscripción:** un modelo que ya pagas (por ejemplo un CLI de
  frontier) aplica su propio esfuerzo y el run lo registra.

## El modelo económico de los workers {#economico}

Los workers pueden correr con un **modelo distinto** al principal. La idea:
**leer y extraer** va a un modelo económico; **decidir** se queda en el principal.
Es una elección tuya y opcional — si no eliges ninguno, los workers **heredan el
modelo principal**.

## La verdad del modelo sale de la ejecución {#verdad-del-modelo}

El **modelo activo se confirma al correr**. Si degrada a un modelo de respaldo,
la Sala lo muestra en vez de esconderlo. Nunca se declara "verde" un modelo
porque "el binario existe": la señal sale del run real. En un sub-agente, el
modelo **se confirma al correr** también (la delegación registra el modelo
real, con gate por hijo y deadline propagado).

## Frontier-only para las tareas exigentes {#frontier-only}

Algunas tareas exigen un **modelo capaz**: la Inspección (armar y validar
piezas) y el propio **Guía padrino**. Ahí el selector pide un modelo frontier
verificado —familia opus-4.8, tu propia API o tu CLI por suscripción— y bloquea
los modelos chicos con una explicación honesta, en vez de dejar que fallen a
mitad de camino. Verde aquí significa: herramientas reales + modelo frontier
verificado. Si la ventana de tu suscripción se agota a mitad de la corrida, se
te dice.

## El Guía padrino y su modelo {#guia-cerebro}

El Guía necesita un modelo frontier porque hace de copiloto de manos. Sus
poderes: **SABE** (lee estos documentos como contexto), **MUESTRA** (te lleva:
abre closets, señala piezas, navega superficies) y **HACE** (control del Cuarto),
siempre preguntando "¿lo hago yo o tú?". La línea que **nunca cruza**: propone y
abre, nunca completa una acción que sale al mundo — eso pasa por ti en La Sala.
(Ver `cuarto.es.md`.)
