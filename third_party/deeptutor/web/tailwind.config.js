/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: "class",
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
        serif: ["var(--font-serif)", "Georgia", "serif"],
      },
      // LA GEOMETRÍA DE ALEPH. La escala por defecto de Tailwind (2·4·6·8·12·16·24) es la de
      // otro sistema: acá el producto tiene SEIS escalones y son los de
      // `product/app/design/aleph-tokens.css` (--r-2xs..--r-xl). Re-apuntar la escala en este
      // único lugar cambia los ~30 sitios que ya escriben `rounded-*` en los componentes, sin
      // tocar un solo JSX — el mismo criterio con el que la paleta entró por `globals.css`.
      // El sistema es de CÁPSULA: 13 en el control, 18 en la fila, 22 en el pozo, 30 en el plano.
      borderRadius: {
        sm: "3px",     // --r-2xs · barra fina, swatch
        DEFAULT: "6px", // --r-xs · chip diminuto
        md: "13px",    // --r-sm · botón, input, ícono cuadrado
        lg: "18px",    // --r-md · tarjeta chica, fila, control
        xl: "22px",    // --r-lg · panel, tarjeta grande
        "2xl": "30px", // --r-xl · plano de contenido, modal, hoja
        "3xl": "30px", // el sistema no tiene un escalón por encima del plano
      },
      // EL COLOR POR DEFECTO DEL BORDE. Un `border` a secas (sin `border-<color>`) no elige
      // color: Tailwind lo deja en `currentColor`, así que el borde salía pintado con la TINTA
      // del texto — un filete blanco #F5F5F6 alrededor de cada tarjeta en oscuro. Medido en
      // 29 de las 44 rutas del workspace. El sistema de Aleph prohíbe la línea (la jerarquía
      // es sombra + radio), así que el default cae en `--border`, que ya es `transparent` en
      // los dos temas. Los bordes que SÍ son intencionales siguen funcionando: nombran su
      // color (`border-amber-300`, `border-[var(--primary)]`) y ganan por especificidad.
      borderColor: {
        DEFAULT: "var(--border)",
      },
      colors: {
        border: "var(--border)",
        input: "var(--input)",
        ring: "var(--ring)",
        background: "var(--background)",
        foreground: "var(--foreground)",
        primary: {
          DEFAULT: "var(--primary)",
          foreground: "var(--primary-foreground)",
        },
        secondary: {
          DEFAULT: "var(--secondary)",
          foreground: "var(--secondary-foreground)",
        },
        destructive: {
          DEFAULT: "var(--destructive)",
          foreground: "var(--destructive-foreground)",
        },
        muted: {
          DEFAULT: "var(--muted)",
          foreground: "var(--muted-foreground)",
        },
        accent: {
          DEFAULT: "var(--accent)",
          foreground: "var(--accent-foreground)",
        },
        popover: {
          DEFAULT: "var(--popover)",
          foreground: "var(--popover-foreground)",
        },
        card: {
          DEFAULT: "var(--card)",
          foreground: "var(--card-foreground)",
        },
      },
      backgroundImage: {
        "gradient-radial": "radial-gradient(var(--tw-gradient-stops))",
        "gradient-conic":
          "conic-gradient(from 180deg at 50% 50%, var(--tw-gradient-stops))",
      },
    },
  },
  plugins: [],
};
