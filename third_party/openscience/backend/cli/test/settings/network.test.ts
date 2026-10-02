import { afterEach, expect, test } from "bun:test"
import { Network } from "../../src/settings/network"

afterEach(async () => {
  await Network.set({ allowlistEnabled: false, enabled: ["package-management"], custom: [] })
})

test("domainAllowed accepts exact domains and subdomains only", () => {
  expect(Network.domainAllowed("example.com", ["example.com"])).toBe(true)
  expect(Network.domainAllowed("api.example.com", ["example.com"])).toBe(true)
  expect(Network.domainAllowed("badexample.com", ["example.com"])).toBe(false)
})

test("assertAllowed is advisory when the allow-list is disabled", async () => {
  await Network.set({ allowlistEnabled: false, enabled: [], custom: [] })
  await expect(Network.assertAllowed("https://blocked.test/resource")).resolves.toBeUndefined()
})

test("assertAllowed blocks hosts outside the effective allow-list", async () => {
  await Network.set({ allowlistEnabled: true, enabled: [], custom: ["example.com"] })

  await expect(Network.assertAllowed("https://api.example.com/resource")).resolves.toBeUndefined()
  await expect(Network.assertAllowed("https://blocked.test/resource")).rejects.toThrow("allow-list")
})
