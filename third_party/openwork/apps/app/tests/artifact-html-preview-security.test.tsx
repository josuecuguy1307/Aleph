import { describe, expect, test } from "bun:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import {
  HTML_PREVIEW_SANDBOX,
  HTMLPreview,
} from "../src/react-app/domains/session/artifacts/preview";

function render(element: React.ReactElement) {
  return renderToStaticMarkup(element);
}

describe("HTMLPreview security boundary", () => {
  test("keeps text artifacts interactive without inheriting the renderer origin", () => {
    const html = render(
      <HTMLPreview
        type="text"
        title="interactive.html"
        content={'<button onclick="document.body.dataset.clicked=\'yes\'">Run</button>'}
      />,
    );

    expect(HTML_PREVIEW_SANDBOX).toBe("allow-scripts");
    expect(html).toContain('sandbox="allow-scripts"');
    expect(html).not.toContain("allow-same-origin");
    expect(html).toContain("srcDoc");
    expect(html).toContain("onclick");
  });

  test("applies the same opaque-origin policy to binary HTML artifacts", () => {
    const html = render(
      <HTMLPreview
        type="binary"
        title="binary.html"
        url="blob:http://127.0.0.1:8330/example"
      />,
    );

    expect(html).toContain('sandbox="allow-scripts"');
    expect(html).not.toContain("allow-same-origin");
    expect(html).toContain('src="blob:http://127.0.0.1:8330/example"');
  });
});
