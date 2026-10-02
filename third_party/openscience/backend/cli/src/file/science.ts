import path from "node:path"
import z from "zod"

export namespace ScienceFile {
  export const Format = z.enum(["bam", "cram", "h5ad", "loom"])
  export type Format = z.infer<typeof Format>

  export const Inspection = z.object({
    format: Format,
    name: z.string(),
    size: z.number(),
    modified: z.number(),
    signature: z.boolean(),
    index: z.string().optional(),
    tool: z.object({
      name: z.string(),
      available: z.boolean(),
      detail: z.string().optional(),
    }),
    details: z.record(z.string(), z.unknown()),
  })
  export type Inspection = z.infer<typeof Inspection>

  const python = String.raw`
import json, sys
try:
    import h5py
except Exception as exc:
    print(json.dumps({"error": "h5py is not available", "detail": str(exc)}))
    raise SystemExit(2)

target = sys.argv[1]
result = {"groups": [], "datasets": [], "attributes": {}, "summary": {}}

def clean(value):
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [clean(item) for item in value[:50]]
    return str(value)

def text(value):
    value = clean(value)
    return str(value) if value is not None else ""

def labels(handle, key, indices):
    if not key or "obs" not in handle:
        return []
    value = handle["obs"].get(key)
    if value is None:
        return []
    try:
        if isinstance(value, h5py.Group) and "codes" in value and "categories" in value:
            codes = value["codes"][indices]
            categories = value["categories"][:]
            return [text(categories[int(code)]) if int(code) >= 0 and int(code) < len(categories) else "" for code in codes]
        return [text(item) for item in value[indices]]
    except Exception:
        return []

with h5py.File(target, "r") as handle:
    result["attributes"] = {str(key): clean(value) for key, value in list(handle.attrs.items())[:50]}

    def visit(name, value):
        if len(result["groups"]) + len(result["datasets"]) >= 500:
            return
        if isinstance(value, h5py.Group):
            result["groups"].append(name)
            return
        result["datasets"].append({
            "path": name,
            "shape": list(value.shape),
            "dtype": str(value.dtype),
            "bytes": int(value.size * value.dtype.itemsize),
        })

    handle.visititems(visit)
    matrix = handle.get("X")
    if matrix is None:
        matrix = handle.get("matrix")
    if matrix is not None and hasattr(matrix, "shape"):
        result["summary"]["matrix"] = list(matrix.shape)
    if "obs" in handle:
        obs_index = handle["obs"].get("_index")
        if obs_index is not None:
            result["summary"]["observations"] = len(obs_index)
    if "var" in handle:
        var_index = handle["var"].get("_index")
        if var_index is not None:
            result["summary"]["variables"] = len(var_index)
    if matrix is not None and hasattr(matrix, "shape") and len(matrix.shape) >= 2:
        result["summary"].setdefault("observations", int(matrix.shape[0]))
        result["summary"].setdefault("variables", int(matrix.shape[1]))
    if "obsm" in handle:
        result["summary"]["embeddings"] = list(handle["obsm"].keys())[:100]
        preferred = ["X_umap", "X_tsne", "X_pca", "spatial"]
        names = list(handle["obsm"].keys())
        selected = next((name for name in preferred if name in names), names[0] if names else None)
        value = handle["obsm"].get(selected) if selected else None
        if value is not None and isinstance(value, h5py.Dataset) and len(value.shape) == 2 and value.shape[1] >= 2:
            total = int(value.shape[0])
            count = min(total, 2500)
            indices = [int(index * total / count) for index in range(count)] if count else []
            coords = value[indices, :2] if indices else []
            label_names = ["cell_type", "celltype", "leiden", "louvain", "cluster", "batch"]
            label_key = next((name for name in label_names if "obs" in handle and name in handle["obs"]), None)
            categories = labels(handle, label_key, indices)
            result["embedding"] = {
                "name": selected,
                "label": label_key,
                "total": total,
                "points": [
                    {
                        "x": float(point[0]),
                        "y": float(point[1]),
                        **({"label": categories[index]} if index < len(categories) and categories[index] else {}),
                    }
                    for index, point in enumerate(coords)
                ],
            }
    if "layers" in handle:
        result["summary"]["layers"] = list(handle["layers"].keys())[:100]
    if "row_attrs" in handle:
        result["summary"]["row_attributes"] = list(handle["row_attrs"].keys())[:100]
    if "col_attrs" in handle:
        result["summary"]["column_attributes"] = list(handle["col_attrs"].keys())[:100]
        if "embedding" not in result:
            candidates = [
                (name, handle["col_attrs"].get(name))
                for name in ["X_umap", "UMAP", "Embedding", "_Embedding", "TSNE"]
                if name in handle["col_attrs"]
            ]
            selected = candidates[0] if candidates else None
            if selected and isinstance(selected[1], h5py.Dataset) and len(selected[1].shape) == 2 and selected[1].shape[1] >= 2:
                value = selected[1]
                total = int(value.shape[0])
                count = min(total, 2500)
                indices = [int(index * total / count) for index in range(count)] if count else []
                coords = value[indices, :2] if indices else []
                result["embedding"] = {
                    "name": selected[0],
                    "total": total,
                    "points": [{"x": float(point[0]), "y": float(point[1])} for point in coords],
                }

print(json.dumps(result))
`

  export function format(file: string): Format | undefined {
    const extension = path.extname(file).slice(1).toLowerCase()
    return Format.options.find((value) => value === extension)
  }

  export function binary(file: string): boolean {
    return format(file) !== undefined
  }

  export async function inspect(full: string, relative: string): Promise<Inspection> {
    const kind = format(relative)
    if (!kind) throw new Error(`Unsupported scientific binary format`)
    const file = Bun.file(full)
    if (!(await file.exists())) throw new Error(`File not found: ${relative}`)
    const stat = await file.stat()
    const bytes = new Uint8Array(await file.slice(0, 16).arrayBuffer())
    const base = {
      format: kind,
      name: path.basename(relative),
      size: stat.size,
      modified: stat.mtimeMs,
    }
    if (kind === "h5ad" || kind === "loom") return inspectHdf5(full, base, bytes)
    return inspectAlignment(full, relative, base, bytes)
  }

  async function inspectHdf5(
    full: string,
    base: Pick<Inspection, "format" | "name" | "size" | "modified">,
    bytes: Uint8Array,
  ): Promise<Inspection> {
    const bin = Bun.which("python3") ?? Bun.which("python")
    const signature = [0x89, 0x48, 0x44, 0x46, 0x0d, 0x0a, 0x1a, 0x0a].every((value, index) => bytes[index] === value)
    if (!bin) {
      return {
        ...base,
        signature,
        tool: { name: "h5py", available: false, detail: "Python is not available on PATH" },
        details: {},
      }
    }
    const result = await command([bin, "-c", python, full], 20_000)
    const data = result.code === 0 ? json(result.stdout) : undefined
    return {
      ...base,
      signature,
      tool: {
        name: "h5py",
        available: result.code === 0,
        detail:
          result.code === 0
            ? `inspected with ${path.basename(bin)}`
            : detail(result.stdout, result.stderr) ||
              "Install h5py in the Python environment used to launch OpenScience",
      },
      details: data ?? {},
    }
  }

  async function inspectAlignment(
    full: string,
    relative: string,
    base: Pick<Inspection, "format" | "name" | "size" | "modified">,
    bytes: Uint8Array,
  ): Promise<Inspection> {
    const bin = Bun.which("samtools")
    const cram = base.format === "cram"
    const signature = cram
      ? bytes[0] === 0x43 && bytes[1] === 0x52 && bytes[2] === 0x41 && bytes[3] === 0x4d
      : bytes[0] === 0x1f && bytes[1] === 0x8b
    const index = await findIndex(full, relative, cram)
    const version = cram && signature ? `${bytes[4] ?? 0}.${bytes[5] ?? 0}` : undefined
    if (!bin) {
      return {
        ...base,
        signature,
        index,
        tool: { name: "samtools", available: false, detail: "Install samtools to inspect headers and references" },
        details: version ? { version } : {},
      }
    }
    const header = await command([bin, "view", "-H", full], 20_000)
    const refs = header.stdout
      .split(/\r?\n/)
      .filter((line) => line.startsWith("@SQ"))
      .map((line) =>
        Object.fromEntries(
          line
            .split("\t")
            .slice(1)
            .map((part) => part.split(":", 2)),
        ),
      )
      .map((record) => ({ name: record.SN ?? "", length: Number(record.LN) || 0 }))
    const hd = header.stdout
      .split(/\r?\n/)
      .find((line) => line.startsWith("@HD"))
      ?.split("\t")
      .slice(1)
      .map((part) => part.split(":", 2))
    const stats = index ? await command([bin, "idxstats", full], 20_000) : undefined
    const chromosomes =
      stats?.code === 0
        ? stats.stdout
            .split(/\r?\n/)
            .filter(Boolean)
            .map((line) => line.split("\t"))
            .filter((row) => row[0] !== "*")
            .map((row) => ({
              name: row[0] ?? "",
              length: Number(row[1]) || 0,
              mapped: Number(row[2]) || 0,
              unmapped: Number(row[3]) || 0,
            }))
        : []
    return {
      ...base,
      signature,
      index,
      tool: {
        name: "samtools",
        available: header.code === 0,
        detail: header.code === 0 ? "header inspected locally" : detail(header.stdout, header.stderr),
      },
      details: {
        ...(version ? { version } : {}),
        header: hd ? Object.fromEntries(hd) : {},
        references: refs,
        chromosomes,
      },
    }
  }

  async function findIndex(full: string, relative: string, cram: boolean): Promise<string | undefined> {
    const extension = cram ? ".crai" : ".bai"
    const candidates = [full + extension, full.replace(/\.[^.]+$/, extension)]
    const found = await Promise.all(
      candidates.map(async (candidate) => ((await Bun.file(candidate).exists()) ? candidate : undefined)),
    )
    const value = found.find(Boolean)
    if (!value) return
    return path.join(path.dirname(relative), path.basename(value)).replace(/^\.\//, "")
  }

  async function command(args: string[], timeout: number): Promise<{ code: number; stdout: string; stderr: string }> {
    const process = Bun.spawn(args, { stdout: "pipe", stderr: "pipe" })
    const timer = setTimeout(() => process.kill(), timeout)
    const code = await process.exited
    clearTimeout(timer)
    const [stdout, stderr] = await Promise.all([
      new Response(process.stdout).text(),
      new Response(process.stderr).text(),
    ])
    return { code, stdout, stderr }
  }

  function json(value: string): Record<string, unknown> | undefined {
    return JSON.parse(value) as Record<string, unknown>
  }

  function detail(stdout: string, stderr: string): string {
    return (stderr.trim() || stdout.trim()).slice(0, 500)
  }
}
