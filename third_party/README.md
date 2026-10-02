# `third_party/` — piezas importadas de terceros

Acá vive el código de terceros que Aleph **importa entero**. Nada de esto se escribe a
mano: cada carpeta es un repo ajeno traído tal cual, con su árbol y sus headers de
licencia intactos. El registro de qué hay, de dónde vino y qué se le tocó vive en
[`../ATTRIBUTIONS.md`](../ATTRIBUTIONS.md).

Origen de esta ley: **GATE4-PLAN-Y-CONCLUSIONES-OSS.md · Parte III · Ley de producto 9**
(con la Fase 0.2 del mismo plan).

---

## La ley de importación

1. **Traer entero.** Se importa el repo completo, no fragmentos elegidos a mano.

2. **Carpeta propia, árbol intacto.** Una pieza = una carpeta bajo `third_party/`, con
   la estructura interna del repo de origen sin reacomodar.

3. **Header de licencia intacto.** Ningún encabezado de licencia se borra, se acorta ni
   se reescribe.

4. **Origen declarado.** Toda pieza entra con su fila en `ATTRIBUTIONS.md`: repo, commit,
   licencia, fecha de importación y modificaciones. **Pieza sin fila = pieza que no entró.**

5. **Cero refactor inicial.** En la importación no se renombra, no se reformatea, no se
   reordena, no se "mejora" nada. El diff de la importación es el repo ajeno y nada más.

6. **Tres cirugías, y sólo tres.** Lo permitido es: amputar el agente/chat/BYOK que la
   pieza traiga (el cerebro siempre es Aleph — Ley 2), aplicar la piel de Aleph (Ley 3), y
   **reubicar su navegación** para que el espacio tenga UNA sola barra y no dos.

   Las dos primeras se hacen **por la costura que el propio repo dejó** —sus puntos de
   extensión declarados—. La tercera **puede abrir el cuerpo**, y por eso viene con freno:

   a. **Es REUBICACIÓN, no reimplementación.** Cada ítem que se mueve conserva su handler,
      su estado y su comportamiento. Si un ítem deja de funcionar después de moverlo, el
      trabajo está mal hecho. Lo que no exista en la pieza se declara HUECO; no se pinta.

   b. **Antes de abrir, se mide.** Qué archivos, cuántas líneas, qué se pierde cuando esa
      pieza se re-vendorice, y si hay una forma más chica de conseguir lo mismo. Una perilla
      de config que ya existe le gana siempre a una línea nueva.

   c. **Cada archivo ajeno tocado se anota** en la lista de deuda de re-vendorización, con
      su motivo. La deuda no es opcional: es lo que hace reversible haber abierto el cuerpo.

   d. **El límite sagrado no se mueve.** Piel, superficie y estructura de navegación, sí.
      El motor, las tools, las fuentes de datos y el oficio de la pieza, JAMÁS.

   > Por qué cambió: esta ley se escribió cuando montar por encima era la única vía, y
   > alcanzaba para teñir. Para el frame no alcanza — medido: con la piel prendida, Oficina
   > mostraba DOS barras y DOS cabeceras «Aleph · Oficina», porque lo nuestro se sobreponía
   > a lo suyo en vez de fundirse. El dueño autorizó abrir el cuerpo el 2026-09-07, y pidió
   > que la regla se reescribiera en vez de ignorarse en silencio.

7. **Si se tira, es una carpeta.** Descartar una pieza tiene que ser borrar su carpeta y
   su fila. Si descartarla obliga a desenredar código nuestro, la importación se hizo mal.

---

## Qué NO entra acá

- **Copyleft fuerte (GPL / AGPL).** Jamás como código adentro. Esos motores se usan por
  el **camino Descarga**: proceso aparte, hablado por API/CLI/MCP (plan, Fase 3.3 con
  OpenBB). Acá sólo entra lo que se puede distribuir dentro del producto.
- **Piezas sin archivo de licencia.** Sin `LICENSE` real en el repo de origen no hay
  permiso que heredar: un README que dice "MIT" no es una licencia. Se queda afuera hasta
  que su dueño publique una.
- **Fragmentos.** Si hace falta un pedazo suelto, o entra el repo entero o se
  reimplementa desde el patrón (que es otra cosa, y se declara como tal).
