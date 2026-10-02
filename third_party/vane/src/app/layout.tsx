export const dynamic = 'force-dynamic';

/*
 * [Aleph · Gate 4 · Fase 6 · §6.a.bis] EL ROOT LAYOUT, VACIADO.
 *
 * De este stack se hereda EL MOTOR, JAMÁS LA CARA: «su UI NO se monta — se hereda el
 * motor sin la cara». La cara de la búsqueda ES LA SALA. Lo que quedó en `src/app/` son
 * sólo los `route.ts` de la API; las páginas se extirparon
 * (`third_party/vane/EXTIRPACIONES.md` §1).
 *
 * Next exige un root layout aunque no haya una sola página, así que este archivo no se
 * borra: se vacía. Lo que se fue con él, y por qué:
 *
 *   · `Sidebar`, `SetupWizard`, `ChatProvider`, `ThemeProvider`, `Toaster` — la cara.
 *     Los archivos siguen en el árbol (Ley 5: cero refactor); simplemente ya no los
 *     alcanza ninguna ruta, así que el build no los emite.
 *   · `Montserrat` de `next/font/google` — **una salida a Google en tiempo de build**.
 *     En un producto que se vende como privado, y en una casa que empaqueta offline, una
 *     fuente que se baja de un tercero al compilar no entra.
 *   · `metadata` con el nombre y el claim del producto ajeno — marca (Ley 2.bis / 3.8).
 *   · `configManager.isSetupComplete()` — el asistente de primer arranque de ellos. Acá
 *     la config la escribe el pack en cada `enter`, y no hay a quién preguntarle nada.
 */

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
