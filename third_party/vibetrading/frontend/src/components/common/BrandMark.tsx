export function BrandMark({
  className = "h-6 w-6",
}: {
  className?: string;
}) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 32 32"
      fill="none"
      className={className}
      aria-hidden="true"
    >
      {/* [Aleph · F6 · ley 3.8] Sobrevive el OFICIO —las tres velas ascendentes—, muere
          la PALETA del proyecto de origen (su naranja #EA580C→#F7A316 y su placa). El
          `currentColor` hace que la marca tome el color de la superficie de Aleph donde
          esté puesta, en vez de imponer una identidad ajena. */}
      <line x1="9.5" y1="14" x2="9.5" y2="24.5" stroke="currentColor" strokeOpacity="0.55" strokeWidth="1.8" strokeLinecap="round" />
      <rect x="7.5" y="16" width="4" height="6" rx="1" fill="currentColor" />
      <line x1="16" y1="9.5" x2="16" y2="21.5" stroke="currentColor" strokeOpacity="0.55" strokeWidth="1.8" strokeLinecap="round" />
      <rect x="14" y="11.5" width="4" height="7" rx="1" fill="currentColor" />
      <line x1="22.5" y1="5.5" x2="22.5" y2="18" stroke="currentColor" strokeOpacity="0.55" strokeWidth="1.8" strokeLinecap="round" />
      <rect x="20.5" y="7.5" width="4" height="7.5" rx="1" fill="currentColor" />
    </svg>
  );
}
