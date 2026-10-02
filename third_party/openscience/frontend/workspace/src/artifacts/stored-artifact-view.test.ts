import { expect, test } from "bun:test"

const source = await Bun.file(new URL("./StoredArtifactView.tsx", import.meta.url)).text()

test("keeps text preview loading state reactive", () => {
  expect(source).toContain("<Show when={!props.loading} fallback={<p style={empty()}>Loading preview…</p>}>")
  expect(source).not.toContain("if (props.loading)")
})

test("refreshes an open artifact record after a new immutable version is saved", () => {
  expect(source).toContain('window.addEventListener("openscience:artifacts-changed", refresh)')
  expect(source).toContain("void detailActions.refetch()")
  expect(source).toContain("setVersionID(detail.latest.currentVersionID)")
})

test("does not overclaim immutable artifact review or provenance", () => {
  expect(source).toContain("No reviewer verdict is recorded")
  expect(source).toContain("Starting a review is not a pass")
  expect(source).toContain("`/session/${encodeURIComponent(session)}/review/artifact`")
  expect(source).toContain("body: JSON.stringify({ artifactID: props.artifact.id, versionID: version.id })")
  expect(source).toContain("result?.target?.id !== storedArtifactReviewTargetID(version)")
  expect(source).toContain("finding.target === target")
  expect(source).toContain("Aleph Ciencia does not claim the originating command, model, or environment")
})

test("keeps rename and recoverable deletion in the stored artifact lifecycle", () => {
  expect(source).toContain('method: "PATCH"')
  expect(source).toContain('method: "DELETE"')
  expect(source).toContain("Recoverable from Files for 30 days")
  expect(source).toContain("uiStore.updateSaved(updated)")
  expect(source).toContain("uiStore.closeWorkTab(`saved:${props.artifact.id}`)")
})
