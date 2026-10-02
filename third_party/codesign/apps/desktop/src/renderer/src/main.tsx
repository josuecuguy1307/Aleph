import { initI18n } from '@open-codesign/i18n';
// La letra de la casa reemplaza a las tres familias del proyecto de origen (ley 3 · 3.8).
import './aleph-fonts.css';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import './index.css';
import { installRendererLogBridge } from './lib/renderer-logger';
import { installWebBridge } from './web-bridge';

// Install as early as possible so errors during bootstrap are captured.
installWebBridge();
installRendererLogBridge();

const container = document.getElementById('root');
if (!container) throw new Error('Root element #root not found');
const root = createRoot(container);

/* [rediseño · fase DISEÑO · pieza 11] EL IDIOMA CRUZA CON UNA PALABRA, COMO EL TEMA.
 *
 * POR QUÉ EXISTE ESTE CABLE. El diseño saca las tres pastillas de la barra horizontal y dice
 * que «idioma y tema viven en Appearance». Para el TEMA eso ya era cierto: la casa manda
 * `?aleph_scheme` y el `<head>` de `index.html` lo persiste en la clave que este stack ya
 * usaba. Para el IDIOMA no lo era: Appearance guarda el idioma DE LA CASA y nada lo hacía
 * llegar acá adentro. Apagar el globo sin este cable habría dejado a Diseño sin ninguna forma
 * de cambiar de idioma — que es justo lo que la regla «verificá que el destino existe antes
 * de matarlas» prohíbe. Así que se copia el patrón del tema, que es el sellado para esto.
 *
 * ⚠️ SE PERSISTE, no se aplica y ya. La casa pone el `src` del iframe UNA vez y el router de
 * esta app se lleva el `search` en la primera navegación: `locale.set` lo guarda donde este
 * stack ya guardaba el suyo, así que sobrevive.
 *
 * ⚠️ LA CASA HABLA DOS IDIOMAS Y ESTE STACK CUATRO. `pt-BR` y `zh-CN` quedan alcanzables
 * sólo fuera de Aleph. Es consecuencia de la decisión de diseño —el idioma lo gobierna
 * Appearance— y no un olvido: queda dicho acá y en el reporte.
 */
const IDIOMAS_DE_LA_CASA = ['es', 'en'] as const;

function idiomaDeLaCasa(): string | null {
  try {
    const v = new URLSearchParams(window.location.search).get('aleph_lang');
    return v && (IDIOMAS_DE_LA_CASA as readonly string[]).includes(v) ? v : null;
  } catch {
    return null;
  }
}

async function bootstrap(): Promise<void> {
  let locale = window.codesign ? await window.codesign.locale.getCurrent() : undefined;
  const pedido = idiomaDeLaCasa();
  if (pedido && window.codesign && pedido !== locale) {
    try {
      locale = await window.codesign.locale.set(pedido);
    } catch {
      /* Un idioma que no se pudo guardar no puede impedir que la app arranque: se sigue con
         el que había. Falla visible en consola por el puente de logs, no en la cara. */
    }
  }
  await initI18n(locale);

  root.render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}

void bootstrap();
