# Conectar {#conectar}

Tu agente usa lo que tú le das acceso. Algunas cosas ya funcionan solas; otras te
piden conectar tu cuenta — tú decides, se guarda cifrado y lo quitas cuando
quieras.

## El permiso es tuyo {#permiso}

Cuando un conector necesita tu cuenta, te llevamos al proveedor para que
**autorices tu propia cuenta**. El permiso es tuyo y lo revocas cuando quieras.
Si todavía no iniciaste sesión, guardamos tu conexión bajo una cuenta de prueba
para la demo (cifrada igual); en el producto queda en tu cuenta.

## Las cuatro familias de conexión {#familias}

1. **Sin llave (keyless):** funciona de una, sin credenciales.
2. **Con datos / llave:** pegas una API key y queda lista. La llave se guarda
   cifrada en tu vault; no la pedimos antes de que elijas el modelo o el conector.
3. **OAuth (navegador):** te abre la pestaña del proveedor para que autorices.
4. **Token guiado:** te llevamos a crear una llave nueva en el proveedor y te
   decimos exactamente qué marcar. Copia la llave completa: muchos proveedores
   (por ejemplo Zotero) la muestran una sola vez.

## El catálogo: buscar antes de forjar {#catalogo}

El catálogo mezcla conectores **internos** (listos) y del **registro público**.
Los badges dicen la verdad de cada uno: `listo · sin llave`,
`conectado · listo`, `listo · conecta tu cuenta`, `community · no verificado`.
Escribe un nombre o rubro para buscar también en el registro público.

Al elegir un conector, se **valida** antes de conectar:

- **Verificado como oficial:** puedes conectar tranquilo.
- **No verificado** (sin prueba de dueño): conecta sólo si confías en la fuente.
- **Desconocido:** el registro no conoce ese servicio. Puedes **construir un MCP**
  desde tu API o tus docs.

Si el catálogo público no responde, te mostramos solo los conectores internos y
te pedimos reintentar — **no inventamos resultados** ni forjamos nada a ciegas.

## Cuidado con el impostor {#impostor}

Si el conector oficial verificado es distinto del que elegiste, te avisamos y te
sugerimos conectar **el verificado**. La verificación es contra el dueño real del
servicio, no contra el nombre.

## Construir un MCP con el Motor B {#motor-b}

Si no existe un conector para lo que necesitas, el **Motor B** lo arma desde tu
API o tus docs y lo **valida en vivo**: lo abre, lee sus tools reales y las deja
como piezas equipables en tu Cuarto. Cero teatro — si no conecta, te lo dice. Tú
apruebas antes de equiparlo.
