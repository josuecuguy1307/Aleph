/** Keep OfficeCLI's slide counter aligned with the content actually in view. */
export function restorePptxNavigation(html: string): string {
  if (!html.includes('// OfficeCli HTML Preview Script')) return html;
  const observer = /scrollObserver = new IntersectionObserver\(entries => \{[\s\S]*?\}, \{ root: main, threshold: 0\.3 \}\);/;
  if (!observer.test(html)) return html;
  return html.replace(observer, `
    function updateVisibleSlide() {
        if (isFullscreen) return;
        const frame = main.getBoundingClientRect();
        let best = -1;
        let visiblePixels = 0;
        getContainers().forEach((container, index) => {
            const rect = container.getBoundingClientRect();
            const visible = Math.max(0, Math.min(rect.bottom, frame.bottom) - Math.max(rect.top, frame.top));
            if (visible > visiblePixels) { best = index; visiblePixels = visible; }
        });
        if (best >= 0) setActiveThumb(best);
    }
    scrollObserver = new IntersectionObserver(updateVisibleSlide, { root: main, threshold: [0, 0.3, 0.6, 1] });
    main.addEventListener('scroll', updateVisibleSlide, { passive: true });
    window.addEventListener('resize', () => requestAnimationFrame(updateVisibleSlide));
    requestAnimationFrame(updateVisibleSlide);
  `).replaceAll("scrollIntoView({ behavior: 'smooth', block: 'center' })",
    "scrollIntoView({ behavior: 'smooth', block: 'start' })");
}
