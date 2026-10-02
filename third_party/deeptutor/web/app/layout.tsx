import type { Metadata } from "next";
import "./globals.css";
import ThemeScript from "@/components/ThemeScript";
import ToastViewport from "@/components/common/ToastViewport";
import { AppShellProvider } from "@/context/AppShellContext";
import { I18nClientBridge } from "@/i18n/I18nClientBridge";

// [Gate 4 · F6 · Educación · ley 3] LA LETRA ES LA DE LA CASA. Acá se cargaban Geist y Lora
// por `next/font/google`; ahora Outfit se vendoriza en `globals.css` sobre los woff2 de
// `public/fonts/` —los mismos que sirven las pantallas de Aleph—, y esa hoja publica
// `--font-sans` y `--font-serif`, que es lo que `next/font` publicaba por className.

export const metadata: Metadata = {
  title: "Aleph Educación",
  description: "Tutor de aprendizaje de Aleph",
  // [Gate 4 · F6 · Educación · 3.8] SIN ÍCONO PROPIO. Acá se declaraban tres PNG que son el
  // logo del proyecto de origen, y el favicon se ve en la pestaña del navegador — la
  // superficie más barata de todas para delatar de qué repo vino el workspace. Adentro del
  // lienzo de Aleph la pestaña es la de la casa; el lienzo no necesita ícono propio.
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      data-scroll-behavior="smooth"
    >
      <head>
        <ThemeScript />
        {/* [un solo picker en las siete · 2026-08-22] El cerebro se elige con el chip de
            Aleph, uno para las siete superficies. El picker de este stack no se saca del
            código: el script lo apaga y monta el nuestro en su lugar. Fuera de Aleph el
            archivo es un no-op (LEY 0) y este stack queda intacto.
            Va como <script> crudo y no con next/script porque tiene que correr ANTES de la
            hidratación, igual que ThemeScript, que es el precedente de al lado.
            Ver public/aleph-picker-unico.js. */}
        <script src="/aleph-picker-unico.js" />
        {/* [Aleph · rediseño fase 1 · cable (b)] EL INTERRUPTOR DE LA PIEL. La hoja viaja
            siempre; sólo se aplica con `?aleph_piel=v2` en la URL del iframe. Apagar el
            rediseño no cuesta un build. Fuera de Aleph es un no-op (LEY 0).
            Ver public/aleph-piel.js. */}
        <script src="/aleph-piel.js" />
      </head>
      <body
        className="font-sans bg-[var(--background)] text-[var(--foreground)]"
        suppressHydrationWarning
      >
        <AppShellProvider>
          <I18nClientBridge>{children}</I18nClientBridge>
          <ToastViewport />
        </AppShellProvider>
      </body>
    </html>
  );
}
