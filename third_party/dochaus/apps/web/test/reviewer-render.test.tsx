import { expect, test } from "bun:test"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import Markdown from "../src/components/Markdown"

test("persisted reviewer report renders its table and full content without internal envelope", () => {
  const report = '<task id="fictional" state="completed"><task_result>\n**Revisión ficticia**\n\n| Ubicación | Texto | Corrección |\n|---|---|---|\n| Cláusula 7 | No se fija valor | Siete días; revisión 11–17 |\n| Cierre | estación, Ñ, ü | Fin explícito completo |\n\n1. Conservar las doce cláusulas.\n2. Verificar el anexo completo.\n</task_result></task>'
  const html = renderToStaticMarkup(createElement(Markdown, { children: report }))
  expect(html).toContain("<table>")
  expect(html).toContain("<th>Corrección</th>")
  expect(html).toContain("<td>Fin explícito completo</td>")
  expect(html).toContain("Siete días; revisión 11–17")
  expect(html).toContain("<ol>")
  expect(html).not.toContain("task_result")
  expect(html).not.toContain("fictional")
})
