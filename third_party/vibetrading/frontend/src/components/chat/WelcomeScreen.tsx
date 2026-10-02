import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronDown, TrendingUp, Globe, Sparkles, Users, UserCircle2, NotebookPen, Landmark, Gem } from "lucide-react";
import { useAlephFrame } from "@/components/layout/aleph-frame";

interface Example {
  titleKey: string;
  descKey: string;
  promptKey: string;
}

interface Category {
  labelKey: string;
  icon: React.ReactNode;
  examples: Example[];
}

const CATEGORIES: Category[] = [
  {
    labelKey: "welcome.categories.multiMarketBacktest",
    icon: <TrendingUp className="h-4 w-4" />,
    examples: [
      {
        titleKey: "welcome.examples.crossMarketPortfolio",
        descKey: "welcome.examples.crossMarketPortfolioDesc",
        promptKey: "welcome.examples.crossMarketPortfolioPrompt",
      },
      {
        titleKey: "welcome.examples.btcMacd",
        descKey: "welcome.examples.btcMacdDesc",
        promptKey: "welcome.examples.btcMacdPrompt",
      },
      {
        titleKey: "welcome.examples.usTechMaxDiv",
        descKey: "welcome.examples.usTechMaxDivDesc",
        promptKey: "welcome.examples.usTechMaxDivPrompt",
      },
    ],
  },
  {
    labelKey: "welcome.categories.researchAnalysis",
    icon: <Sparkles className="h-4 w-4" />,
    examples: [
      {
        titleKey: "welcome.examples.multiFactorAlpha",
        descKey: "welcome.examples.multiFactorAlphaDesc",
        promptKey: "welcome.examples.multiFactorAlphaPrompt",
      },
      {
        titleKey: "welcome.examples.optionsGreeks",
        descKey: "welcome.examples.optionsGreeksDesc",
        promptKey: "welcome.examples.optionsGreeksPrompt",
      },
    ],
  },
  {
    labelKey: "welcome.categories.valueInvesting",
    icon: <Gem className="h-4 w-4" />,
    examples: [
      {
        titleKey: "welcome.examples.valueCommittee",
        descKey: "welcome.examples.valueCommitteeDesc",
        promptKey: "welcome.examples.valueCommitteePrompt",
      },
      {
        titleKey: "welcome.examples.bottleneckHunter",
        descKey: "welcome.examples.bottleneckHunterDesc",
        promptKey: "welcome.examples.bottleneckHunterPrompt",
      },
      {
        titleKey: "welcome.examples.thesisTracker",
        descKey: "welcome.examples.thesisTrackerDesc",
        promptKey: "welcome.examples.thesisTrackerPrompt",
      },
      {
        titleKey: "welcome.examples.valuationCheck",
        descKey: "welcome.examples.valuationCheckDesc",
        promptKey: "welcome.examples.valuationCheckPrompt",
      },
    ],
  },
  {
    labelKey: "welcome.categories.swarmTeams",
    icon: <Users className="h-4 w-4" />,
    examples: [
      {
        titleKey: "welcome.examples.investmentCommittee",
        descKey: "welcome.examples.investmentCommitteeDesc",
        promptKey: "welcome.examples.investmentCommitteePrompt",
      },
      {
        titleKey: "welcome.examples.quantStrategyDesk",
        descKey: "welcome.examples.quantStrategyDeskDesc",
        promptKey: "welcome.examples.quantStrategyDeskPrompt",
      },
    ],
  },
  {
    labelKey: "welcome.categories.docWebResearch",
    icon: <Globe className="h-4 w-4" />,
    examples: [
      {
        titleKey: "welcome.examples.earningsReport",
        descKey: "welcome.examples.earningsReportDesc",
        promptKey: "welcome.examples.earningsReportPrompt",
      },
      {
        titleKey: "welcome.examples.macroResearch",
        descKey: "welcome.examples.macroResearchDesc",
        promptKey: "welcome.examples.macroResearchPrompt",
      },
    ],
  },
  {
    labelKey: "welcome.categories.tradeJournal",
    icon: <NotebookPen className="h-4 w-4" />,
    examples: [
      {
        titleKey: "welcome.examples.analyzeBrokerExport",
        descKey: "welcome.examples.analyzeBrokerExportDesc",
        promptKey: "welcome.examples.analyzeBrokerExportPrompt",
      },
      {
        titleKey: "welcome.examples.diagnoseBehavior",
        descKey: "welcome.examples.diagnoseBehaviorDesc",
        promptKey: "welcome.examples.diagnoseBehaviorPrompt",
      },
    ],
  },
  {
    labelKey: "welcome.categories.tradingConnectors",
    icon: <Landmark className="h-4 w-4" />,
    examples: [
      {
        titleKey: "welcome.examples.checkConnector",
        descKey: "welcome.examples.checkConnectorDesc",
        promptKey: "welcome.examples.checkConnectorPrompt",
      },
      {
        titleKey: "welcome.examples.analyzePortfolio",
        descKey: "welcome.examples.analyzePortfolioDesc",
        promptKey: "welcome.examples.analyzePortfolioPrompt",
      },
      {
        titleKey: "welcome.examples.quoteTrend",
        descKey: "welcome.examples.quoteTrendDesc",
        promptKey: "welcome.examples.quoteTrendPrompt",
      },
    ],
  },
  {
    labelKey: "welcome.categories.shadowAccount",
    icon: <UserCircle2 className="h-4 w-4" />,
    examples: [
      {
        titleKey: "welcome.examples.trainShadow",
        descKey: "welcome.examples.trainShadowDesc",
        promptKey: "welcome.examples.trainShadowPrompt",
      },
      {
        titleKey: "welcome.examples.shadowDelta",
        descKey: "welcome.examples.shadowDeltaDesc",
        promptKey: "welcome.examples.shadowDeltaPrompt",
      },
      {
        titleKey: "welcome.examples.shadowReport",
        descKey: "welcome.examples.shadowReportDesc",
        promptKey: "welcome.examples.shadowReportPrompt",
      },
    ],
  },
];

/* [Aleph · 2026-08-11] EL SALUDO DE LA CASA.
 *
 * Portado de `product/app/design/sala/sala.html` (`greetSet()`): Aleph no elige UNO al azar
 * —eso hacían las claves `welcome.greetings.*` de este stack—, sino que los CICLA en siete
 * idiomas. Es un gesto de identidad del producto: quien entra ve a Aleph saludando en su
 * idioma y en varios más. Mismas franjas horarias que la casa (5-12 · 12-19 · resto). */
const SALUDOS = {
  manana: ["Buenos días", "Good morning", "Bonjour", "Buongiorno", "Bom dia", "Guten Morgen", "おはよう"],
  tarde: ["Buenas tardes", "Good afternoon", "Bon après-midi", "Buon pomeriggio", "Boa tarde", "Guten Tag", "こんにちは"],
  noche: ["Buenas noches", "Good evening", "Bonsoir", "Buonasera", "Boa noite", "Guten Abend", "こんばんは"],
} as const;

function saludosDeAhora(): readonly string[] {
  const hora = new Date().getHours();
  if (hora >= 5 && hora < 12) return SALUDOS.manana;
  if (hora >= 12 && hora < 19) return SALUDOS.tarde;
  return SALUDOS.noche;
}

const QUICK_ACTIONS = [
  {
    titleKey: "welcome.examples.valuationCheck",
    promptKey: "welcome.examples.valuationCheckPrompt",
    icon: <Gem className="h-4 w-4" aria-hidden="true" />,
  },
  {
    titleKey: "welcome.examples.optionsGreeks",
    promptKey: "welcome.examples.optionsGreeksPrompt",
    icon: <Sparkles className="h-4 w-4" aria-hidden="true" />,
  },
  {
    titleKey: "welcome.examples.crossMarketPortfolio",
    promptKey: "welcome.examples.crossMarketPortfolioPrompt",
    icon: <TrendingUp className="h-4 w-4" aria-hidden="true" />,
  },
  {
    titleKey: "welcome.examples.investmentCommittee",
    promptKey: "welcome.examples.investmentCommitteePrompt",
    icon: <Users className="h-4 w-4" aria-hidden="true" />,
  },
] as const;



interface Props {
  onExample: (s: string) => void;
}

export function WelcomeScreen({ onExample }: Props) {
  const { t } = useTranslation();
  /* [Finanzas · el lienzo] Con el frame puesto, el lienzo es el del artboard: mascota,
     saludo y la barrita. Sin frame, esta pantalla queda exactamente como estaba. */
  const alephFrame = useAlephFrame();
  const [saludos] = useState(() => saludosDeAhora());
  // La sugerencia visible rota por QUICK_ACTIONS. Arranca en una al azar para que dos
  // sesiones seguidas no vean lo mismo, y se detiene si la persona pidió menos movimiento
  // (`prefers-reduced-motion`): ahí queda fija la primera, como hace el saludo de La Sala.
  const [indiceSugerencia, setIndiceSugerencia] = useState(
    () => Math.floor(Math.random() * QUICK_ACTIONS.length),
  );
  useEffect(() => {
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    const id = window.setInterval(() => {
      setIndiceSugerencia((i) => (i + 1) % QUICK_ACTIONS.length);
    }, 6000);
    return () => window.clearInterval(id);
  }, []);
  const sugerencia = QUICK_ACTIONS[indiceSugerencia] ?? QUICK_ACTIONS[0];
  const [isExamplesOpen, setIsExamplesOpen] = useState(false);
  const [activeCategory, setActiveCategory] = useState(0);
  const examplesTriggerRef = useRef<HTMLButtonElement>(null);

  return (
    <div className="aleph-lienzo-vacio flex w-full flex-col items-center px-4 pb-14 text-center">
      <div className="w-full max-w-3xl">
        <div className="mx-auto max-w-2xl">
          {/* LA MASCOTA DE ALEPH, sin marco y sobre un halo radial del acento: es la regla
              de `.ds-mark` en `aleph-ds.css`, el glifo nunca lleva caja ni borde. Reemplaza
              al `BrandMark` de velas, que era la marca del proyecto de origen.
              El SALUDO cicla siete idiomas, apilados en la misma caja para que el alto no
              salte entre «こんにちは» y «Bon après-midi».
              El subtítulo («Ask about a stock, a strategy, or your portfolio — I'll pull the
              data…») se quitó: explicaba en letra chica lo que el compositor ya invita a
              hacer, y en este sistema una pantalla vacía dice UNA cosa. */}
          <div className="flex items-center justify-center gap-3">
            <span className="aleph-mark shrink-0" aria-label="Aleph">
              <img src="/aleph-mascot-v2.png" alt="" width={68} height={68} />
            </span>
            <h1 className="aleph-greet" aria-live="polite">
              {saludos.map((saludo, i) => (
                <span key={saludo} className="aleph-g" style={{ animationDelay: `${i * 5}s` }}>
                  {saludo}
                </span>
              ))}
            </h1>
          </div>
        </div>

        {/* [Aleph · 2026-08-11] UNA SOLA SUGERENCIA, Y VA CAMBIANDO.
            Eran CUATRO chips fijos, uno de ellos resaltado: una parrilla de opciones que
            compite con el compositor, que es donde la persona tiene que escribir. El
            sistema de Aleph pide lo contrario —una cosa a la vez— y ya tiene el gesto para
            esto: el saludo de La Sala, que no muestra siete idiomas sino que los CICLA.
            Acá pasa lo mismo con las sugerencias: se ve una, cambia cada 6 segundos, y
            sigue siendo un botón que carga ese prompt en el compositor. Las cuatro siguen
            declaradas en QUICK_ACTIONS y la biblioteca completa sigue estando abajo, en
            «ver todos los ejemplos»: no se pierde ninguna, se muestran de a una. */}
        {/* [Finanzas · el lienzo] LAS DOS CTA SALEN CON EL FRAME PUESTO, y lo dice el propio
            diseño en sus notas: «antes: CTA "Balance a 3-stock portfolio" y "Browse all
            examples" → fuera». El artboard de Finanzas deja el lienzo con la mascota, el
            saludo y el composer, nada más.
            Se APAGAN, no se borran: con el frame off la pantalla queda igual que hoy y la
            biblioteca de ejemplos sigue entera. Misma reversibilidad que el «+» de sesiones. */}
        {!alephFrame.activo && (
        <div
          className="mt-8 flex justify-center"
          role="group"
          aria-label={t("welcome.quickActions" as any)}
        >
          <button
            key={sugerencia.titleKey}
            type="button"
            onClick={() => onExample(t(sugerencia.promptKey as any))}
            className="aleph-sugerencia inline-flex items-center gap-2 rounded-full border border-primary/30 bg-primary/[0.08] px-4 py-2 text-sm text-primary transition-colors hover:border-primary/50 hover:bg-primary/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
          >
            {sugerencia.icon}
            <span>{t(sugerencia.titleKey as any)}</span>
          </button>
        </div>
        )}

        {/* Misma razón que arriba: la puerta a la biblioteca de ejemplos y la biblioteca
            entera se apagan con el frame puesto. Apagar sólo el botón dejaría el panel en el
            DOM sin forma de abrirlo, que es peor que sacarlo. */}
        {!alephFrame.activo && (
        <>
        <button
          ref={examplesTriggerRef}
          type="button"
          aria-expanded={isExamplesOpen}
          aria-controls="welcome-example-library"
          onClick={() => setIsExamplesOpen((open) => !open)}
          className="mt-10 inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
        >
          <span>{t("welcome.browseAllExamples" as any)}</span>
          <ChevronDown
            className={`h-4 w-4 transition-transform duration-300 ${isExamplesOpen ? "rotate-180" : ""}`}
            aria-hidden="true"
          />
        </button>

        <div
          id="welcome-example-library"
          aria-hidden={!isExamplesOpen}
          onKeyDown={(event) => {
            if (event.key !== "Escape" || !isExamplesOpen) return;
            event.preventDefault();
            event.stopPropagation();
            setIsExamplesOpen(false);
            examplesTriggerRef.current?.focus();
          }}
          className={`grid text-left transition-[grid-template-rows,opacity] duration-300 ease-out ${
            isExamplesOpen
              ? "grid-rows-[1fr] opacity-100"
              : "grid-rows-[0fr] opacity-0"
          }`}
        >
          <div className="min-h-0 overflow-hidden">
            {/* One category at a time: a chip tab bar + that category's cards.
                Rendering all 8 categories at once (grid or masonry) reads as
                an unstructured wall — categories have uneven card counts. */}
            <div className="pt-6">
              <div
                className="flex flex-wrap justify-center gap-1.5"
                role="tablist"
                aria-label={t("welcome.browseAllExamples" as any)}
              >
                {CATEGORIES.map((cat, index) => (
                  <button
                    key={cat.labelKey}
                    type="button"
                    role="tab"
                    aria-selected={index === activeCategory}
                    tabIndex={isExamplesOpen ? 0 : -1}
                    onClick={() => setActiveCategory(index)}
                    className={
                      index === activeCategory
                        ? "inline-flex items-center gap-1.5 rounded-full border border-primary/30 bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary"
                        : "inline-flex items-center gap-1.5 rounded-full border border-transparent px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:border-border/60 hover:text-foreground"
                    }
                  >
                    {cat.icon}
                    <span>{t(cat.labelKey as any)}</span>
                  </button>
                ))}
              </div>
              <div role="tabpanel" className="mt-4 grid gap-2 text-left sm:grid-cols-2">
                {CATEGORIES[activeCategory].examples.map((ex) => (
                  <button
                    key={ex.titleKey}
                    type="button"
                    tabIndex={isExamplesOpen ? 0 : -1}
                    onClick={() => onExample(t(ex.promptKey as any))}
                    className="block w-full rounded-xl border border-border/60 px-3 py-2.5 text-left transition-colors hover:border-primary/40 hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
                  >
                    <span className="text-sm font-medium leading-snug text-foreground">
                      {t(ex.titleKey as any)}
                    </span>
                    <span className="mt-0.5 block text-xs leading-snug text-muted-foreground">
                      {t(ex.descKey as any)}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
        </>
        )}
      </div>
    </div>
  );
}
