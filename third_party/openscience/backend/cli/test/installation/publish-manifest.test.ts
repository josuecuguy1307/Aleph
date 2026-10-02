import { describe, expect, test } from "bun:test"
import { createWrapperPackageManifest } from "../../script/publish-manifest"

describe("wrapper package manifest", () => {
  test("preserves source optional dependencies while adding platform packages", () => {
    const manifest = createWrapperPackageManifest({
      source: {
        name: "@synsci/openscience",
        optionalDependencies: {
          "@synsci/atlas": "^0.13.2",
          "@synsci/companion": "^1.2.3",
        },
      },
      version: "1.2.3",
      binaries: {
        "@synsci/openscience-darwin-arm64": "1.2.3",
        "@synsci/openscience-linux-x64": "1.2.3",
      },
    })

    expect(manifest.optionalDependencies).toEqual({
      "@synsci/atlas": "^0.13.2",
      "@synsci/companion": "^1.2.3",
      "@synsci/openscience-darwin-arm64": "1.2.3",
      "@synsci/openscience-linux-x64": "1.2.3",
    })
  })

  test("keeps postinstall verification advisory when lifecycle scripts are enabled", () => {
    const manifest = createWrapperPackageManifest({
      source: {
        name: "@synsci/openscience",
      },
      version: "1.2.3",
      binaries: {
        "@synsci/openscience-darwin-arm64": "1.2.3",
      },
    })

    expect(manifest.scripts.postinstall).toEndWith("|| exit 0")
  })
})
