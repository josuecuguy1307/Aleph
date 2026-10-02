import type { Config } from "tailwindcss";

export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        border: "hsl(var(--border))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        muted: { DEFAULT: "hsl(var(--muted))", foreground: "hsl(var(--muted-foreground))" },
        primary: { DEFAULT: "hsl(var(--primary))", foreground: "hsl(var(--primary-foreground))" },
        destructive: { DEFAULT: "hsl(var(--destructive))", foreground: "hsl(var(--destructive-foreground))" },
        card: { DEFAULT: "hsl(var(--card))", foreground: "hsl(var(--card-foreground))" },
        popover: { DEFAULT: "hsl(var(--popover))", foreground: "hsl(var(--popover-foreground))" },
        success: "hsl(var(--success))",
        danger: "hsl(var(--danger))",
        warning: "hsl(var(--warning))",
        info: "hsl(var(--info))",
      },
      fontFamily: {
        // [Gate 4 · F6 · Finanzas · ley 3] LA LETRA ES LA DE LA CASA. Estaba Inter, que era
        // la del proyecto de origen; Outfit se vendoriza en `index.html` con los mismos
        // woff2 que sirven las pantallas de Aleph.
        sans: ["Outfit", "system-ui", "sans-serif"],
        // El titular de bienvenida iba en SERIF de 34px — y en este sistema la serif es
        // gesto de MARCA (Aleph la reserva para su wordmark, que vive en la barra de la
        // casa, no acá adentro). El titular pasa a la sans de la casa.
        serif: ["Outfit", "system-ui", "sans-serif"],
        // La mono es la de la casa: stack de sistema, sin webfont. Se fueron con ella los
        // 6 woff2 de JetBrains Mono, que era la mono del proyecto de origen.
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      /* [Aleph] La escala del sistema, EXPLÍCITA. La derivación de shadcn
         (`calc(var(--radius) - 2px)`) producía 16px y 14px, que no son escalones de Aleph:
         acá hay seis y son 3·6·13·18·22·30. Un `rounded-md` tiene que caer en 13 (el
         control) y `rounded-lg` en 18 (la fila), no en un valor intermedio. */
      borderRadius: {
        DEFAULT: "13px",  // `rounded` a secas era 4px, el default de Tailwind
        sm: "6px",
        md: "13px",
        lg: "18px",
        xl: "22px",
        "2xl": "30px",
      },
    },
  },
  plugins: [require("@tailwindcss/typography")],
} satisfies Config;
