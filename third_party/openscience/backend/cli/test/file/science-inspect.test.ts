import { describe, expect, test } from "bun:test"
import path from "node:path"
import { File } from "../../src/file"
import { Instance } from "../../src/project/instance"
import { tmpdir } from "../fixture/fixture"

describe("File.inspect", () => {
  test("recognizes H5AD containers and reports local inspection capabilities", async () => {
    await using tmp = await tmpdir({
      init: async (directory) => {
        const signature = Uint8Array.from([0x89, 0x48, 0x44, 0x46, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 0])
        await Bun.write(path.join(directory, "cells.h5ad"), signature)
      },
    })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        const result = await File.inspect("cells.h5ad")
        expect(result).toMatchObject({
          format: "h5ad",
          name: "cells.h5ad",
          size: 12,
          signature: true,
          tool: { name: "h5py" },
        })
        expect(typeof result.tool.available).toBe("boolean")
      },
    })
  })

  test("recognizes CRAM version bytes and adjacent indexes", async () => {
    await using tmp = await tmpdir({
      init: async (directory) => {
        await Bun.write(path.join(directory, "sample.cram"), Uint8Array.from([0x43, 0x52, 0x41, 0x4d, 3, 1, 0, 0]))
        await Bun.write(path.join(directory, "sample.cram.crai"), "index")
      },
    })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        const result = await File.inspect("sample.cram")
        expect(result).toMatchObject({
          format: "cram",
          signature: true,
          index: "sample.cram.crai",
          details: { version: "3.1" },
          tool: { name: "samtools" },
        })
      },
    })
  })

  test("recognizes BAM and conventional index names", async () => {
    await using tmp = await tmpdir({
      init: async (directory) => {
        await Bun.write(path.join(directory, "sample.bam"), Uint8Array.from([0x1f, 0x8b, 8, 4, 0, 0, 0, 0]))
        await Bun.write(path.join(directory, "sample.bai"), "index")
      },
    })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        const result = await File.inspect("sample.bam")
        expect(result).toMatchObject({
          format: "bam",
          signature: true,
          index: "sample.bai",
          tool: { name: "samtools" },
        })
      },
    })
  })

  test("rejects unsupported extensions and paths outside the project", async () => {
    await using tmp = await tmpdir({
      init: async (directory) => {
        await Bun.write(path.join(directory, "notes.bin"), "content")
      },
    })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        await expect(File.inspect("notes.bin")).rejects.toThrow("Unsupported scientific binary format")
        await expect(File.inspect("../../outside.h5ad")).rejects.toThrow("Access denied")
      },
    })
  })
})

describe("large binary reads", () => {
  test("returns metadata instead of base64-loading files above the preview limit", async () => {
    await using tmp = await tmpdir({
      init: async (directory) => {
        const file = Bun.file(path.join(directory, "large.bam"))
        const writer = file.writer()
        writer.write(Uint8Array.from([0x1f, 0x8b, 8, 4]))
        writer.write(new Uint8Array(16 * 1024 * 1024))
        await writer.end()
      },
    })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        const result = await File.read("large.bam")
        expect(result.encoding).toBe("base64")
        expect(result.content).toBe("")
        expect(result.truncated).toBe(true)
        expect(result.size).toBeGreaterThan(16 * 1024 * 1024)
      },
    })
  })
})

describe("large text reads", () => {
  test("returns a bounded read-only preview instead of loading the whole scientific file", async () => {
    await using tmp = await tmpdir({
      init: async (directory) => {
        const writer = Bun.file(path.join(directory, "variants.vcf")).writer()
        const chunk = new TextEncoder().encode("chr1\t1\t.\tA\tG\t60\tPASS\tDP=20\n".repeat(32_768))
        for (const _ of Array.from({ length: 10 })) writer.write(chunk)
        await writer.end()
      },
    })

    await Instance.provide({
      directory: tmp.path,
      fn: async () => {
        const result = await File.read("variants.vcf")
        expect(result.truncated).toBe(true)
        expect(result.size).toBeGreaterThan(8 * 1024 * 1024)
        expect(new TextEncoder().encode(result.content).byteLength).toBeLessThanOrEqual(8 * 1024 * 1024)
      },
    })
  })
})
