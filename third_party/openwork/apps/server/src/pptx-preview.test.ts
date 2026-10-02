import { describe, expect, test } from "bun:test";
import { runInNewContext } from "node:vm";
import { restorePptxNavigation } from "./pptx-preview.js";

const script = `// OfficeCli HTML Preview Script
let scrollObserver;
scrollObserver = new IntersectionObserver(entries => {
  entries.forEach(e => {
    if (e.isIntersecting && e.intersectionRatio > 0.3) {
      const idx = getContainers().indexOf(e.target);
      if (idx >= 0) setActiveThumb(idx);
    }
  });
}, { root: main, threshold: 0.3 });`;

describe("PPTX preview navigation", () => {
  test("uses actual visible pixels instead of stale intersection entries after resize", () => {
    let selected = -1;
    let callback: (entries: unknown[]) => void = () => {};
    const listeners = new Map<string, () => void>();
    let positions = [{ top: 0, bottom: 1200 }, { top: 1220, bottom: 2440 }];
    const containers = positions.map((_, index) => ({ getBoundingClientRect: () => positions[index] }));
    const main = {
      getBoundingClientRect: () => ({ top: 0, bottom: 600 }),
      addEventListener: (event: string, handler: () => void) => listeners.set(event, handler),
    };
    runInNewContext(restorePptxNavigation(script), {
      main, isFullscreen: false, getContainers: () => containers,
      setActiveThumb: (index: number) => { selected = index; },
      IntersectionObserver: class {
        constructor(handler: typeof callback) { callback = handler; }
      },
      window: { addEventListener: (event: string, handler: () => void) => listeners.set(event, handler) },
      requestAnimationFrame: (handler: () => void) => handler(),
    });
    callback([{ target: containers[1], isIntersecting: true, intersectionRatio: 0.5 }]);
    expect(selected).toBe(0);
    positions = [{ top: -1000, bottom: 200 }, { top: 220, bottom: 1440 }];
    listeners.get("scroll")!();
    expect(selected).toBe(1);
    positions = [{ top: 0, bottom: 1200 }, { top: 1220, bottom: 2440 }];
    listeners.get("resize")!();
    expect(selected).toBe(0);
  });

  test("opens sections at their beginning and preserves original slide content", () => {
    const html = script + `<img src="data:image/png;base64,example">\ncontainers[idx].scrollIntoView({ behavior: 'smooth', block: 'center' });`;
    const fixed = restorePptxNavigation(html);
    expect(fixed).toContain("block: 'start'");
    expect(fixed).toContain('<img src="data:image/png;base64,example">');
    expect(restorePptxNavigation(fixed)).toBe(fixed);
    expect(restorePptxNavigation("<html>other preview</html>")).toBe("<html>other preview</html>");
  });
});
