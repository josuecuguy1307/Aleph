import { expect, test } from "bun:test"

const source = await Bun.file(new URL("./app.tsx", import.meta.url)).text()

test("the launch screen stays in the global sync provider owner tree", () => {
  expect(source).toContain('import Home from "@/pages/home"')
  expect(source).not.toContain('lazy(() => import("@/pages/home"))')
  expect(source.indexOf("<GlobalSyncProvider>")).toBeLessThan(source.indexOf("<Router"))
  expect(source.indexOf("<Router")).toBeLessThan(source.indexOf("<Home />"))
})
