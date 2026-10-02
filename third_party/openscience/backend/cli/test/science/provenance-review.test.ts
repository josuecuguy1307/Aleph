import { expect, test } from "bun:test"
import { Instance } from "../../src/project/instance"
import { Provenance } from "../../src/science/provenance/store"
import { Review } from "../../src/science/provenance/review"
import { tmpdir } from "../fixture/fixture"

const scope = () => ({ projectID: Instance.project.id, directory: Instance.directory })

test("findings carry message linkage and walk the open → addressed → confirmed lifecycle", async () => {
  await using tmp = await tmpdir({ git: true })
  await Instance.provide({
    directory: tmp.path,
    fn: async () => {
      const target = await Provenance.recordOwned(scope(), {
        kind: "artifact",
        label: "results table",
        artifactType: "dataset",
      } as Parameters<typeof Provenance.record>[0])

      const { node } = await Review.record({
        target: target.id,
        finding: {
          claim: "AUC = 0.99",
          issue: "No producing run recorded for this number",
          severity: "blocking",
          evidence: "provenance graph has no run linked to the table",
        },
        reviewer: "reviewer",
        sessionID: "ses_review_test",
        messageID: "msg_review_1",
        callID: "call_review_1",
        ...scope(),
      })
      expect(node.meta?.messageID).toBe("msg_review_1")
      expect(node.meta?.callID).toBe("call_review_1")

      const open = await Review.list(scope())
      expect(open.find((entry) => entry.finding.id === node.id)?.status).toBe("open")

      // A fix is recorded — the finding becomes addressed, not closed.
      await Review.resolve({
        finding: node.id,
        actor: "Aayam",
        reason: "Re-ran the analysis and attached the producing run",
        ...scope(),
      })
      const addressed = await Review.list(scope())
      const entry = addressed.find((item) => item.finding.id === node.id)
      expect(entry?.status).toBe("addressed")
      expect(entry?.resolution?.actor).toBe("Aayam")

      // Only a LATER reviewer pass that verifies the target confirms it.
      await Review.record({
        target: target.id,
        finding: {
          claim: "AUC = 0.99",
          issue: "verified",
          severity: "info",
          evidence: "producing run run-123 now linked with matching output hash",
        },
        verdict: "supports",
        reviewer: "reviewer",
        ...scope(),
      })
      const confirmed = await Review.list(scope())
      expect(confirmed.find((item) => item.finding.id === node.id)?.status).toBe("confirmed")
    },
  })
})

test("resolve rejects passed checks and unknown findings", async () => {
  await using tmp = await tmpdir({ git: true })
  await Instance.provide({
    directory: tmp.path,
    fn: async () => {
      const target = await Provenance.recordOwned(scope(), {
        kind: "artifact",
        label: "figure",
        artifactType: "figure",
      } as Parameters<typeof Provenance.record>[0])
      const passed = await Review.record({
        target: target.id,
        finding: { claim: "figure matches data", issue: "verified", severity: "info", evidence: "checked bytes" },
        verdict: "supports",
        ...scope(),
      })

      await expect(
        Review.resolve({ finding: passed.node.id, actor: "Aayam", reason: "n/a", ...scope() }),
      ).rejects.toThrow("passed check")
      await expect(Review.resolve({ finding: "missing", actor: "Aayam", reason: "n/a", ...scope() })).rejects.toThrow(
        "not a reviewer finding",
      )
    },
  })
})
