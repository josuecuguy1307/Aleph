import { expect, test } from "bun:test"
import { networkEndpoint } from "./Network"

test("global network settings do not select a filesystem project", () => {
  const endpoint = new URL(networkEndpoint("http://127.0.0.1:4096/"))

  expect(endpoint.pathname).toBe("/settings/network")
  expect([...endpoint.searchParams]).toEqual([])
})
