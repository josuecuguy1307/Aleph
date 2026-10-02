# La barra de título — por qué estos tres campos

> Esta nota vivía DENTRO de `tauri.conf.json` como `_comment_barra`, y el primer build del
> rediseño la rechazó: el schema de Tauri es `additionalProperties: false` en
> `app > windows > 0`. JSON no tiene comentarios y este schema no perdona: la explicación
> vive acá y la config queda limpia.

[rediseño · fase 1] LA BARRA DE TÍTULO DEL ESTÁNDAR: #2b2b29 con Aleph centrado y
los tres semáforos a la izquierda.
· titleBarStyle Transparent — el schema de Tauri lo define textual: «Makes the title
  bar transparent, so the window background color is shown instead. Useful if you
  don't need to have actual HTML under the title bar. This lets you avoid the caveats
  of using TitleBarStyle::Overlay». Es exactamente el caso: no queremos contenido web
  debajo de la barra, sólo que tome nuestro color.
· hiddenTitle false (el default) — el título sigue visible y macOS lo centra solo.
· backgroundColor #2b2b29 — es el color que la barra transparente muestra.
SIN VERIFICAR EN PANTALLA: pide recompilar la cáscara Tauri y el disco tiene 17 GB
libres contra los ~42 GB del build. Va commiteado y declarado como NO MEDIDO: leer un
schema dice qué ACEPTA la config, no qué se VE. Se mira en el primer build.
