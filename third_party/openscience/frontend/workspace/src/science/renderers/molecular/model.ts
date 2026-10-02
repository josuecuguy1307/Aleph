export interface MolecularSource {
  format: string
  url?: string
  raw?: string
  binary?: boolean
}

export interface ElementCount {
  element: string
  count: number
}

export interface MolecularSummary {
  format: string
  source: "inline" | "remote"
  atomCount?: number
  bondCount?: number
  moleculeCount?: number
  chainCount?: number
  residueCount?: number
  modelCount?: number
  elements: ElementCount[]
  warnings: string[]
}

const formats: Record<string, { format: string; binary?: boolean }> = {
  pdb: { format: "pdb" },
  ent: { format: "pdb" },
  cif: { format: "mmcif" },
  mmcif: { format: "mmcif" },
  bcif: { format: "mmcif", binary: true },
  pdbqt: { format: "pdbqt" },
  gro: { format: "gro" },
  xyz: { format: "xyz" },
  sdf: { format: "sdf" },
  mol: { format: "mol" },
  mol2: { format: "mol2" },
}

function format(value: string): { format: string; binary?: boolean } {
  const key = value.toLowerCase()
  return formats[key] ?? { format: key }
}

function formatFromUrl(url: string): { format: string; binary?: boolean } | undefined {
  const clean = url.split(/[?#]/)[0]
  const index = clean.lastIndexOf(".")
  if (index < 0) return
  return formats[clean.slice(index + 1).toLowerCase()]
}

function rcsbUrl(id: string): string {
  return `https://files.rcsb.org/download/${id.trim().toUpperCase()}.cif`
}

export function narrowMolecularSource(data: unknown, kind: string): MolecularSource | undefined {
  const fallback = kind === "chem-3d" ? "sdf" : "pdb"
  if (typeof data === "string") {
    const value = data.trim()
    if (/^[0-9A-Za-z]{4}$/.test(value)) return { url: rcsbUrl(value), format: "mmcif" }
    return { raw: data, format: fallback }
  }
  if (!data || typeof data !== "object" || Array.isArray(data)) return
  const row = data as Record<string, unknown>
  const inline = ["pdb", "cif", "mmcif", "sdf", "mol2", "mol", "xyz"]
  for (const key of inline) {
    if (typeof row[key] !== "string") continue
    return { raw: row[key], ...format(key) }
  }
  const explicit = typeof row.format === "string" ? format(row.format) : undefined
  const text = row.data ?? row.inline ?? row.text
  if (typeof text === "string") return { raw: text, ...(explicit ?? format(fallback)) }
  if (typeof row.url === "string") {
    const guess = formatFromUrl(row.url)
    return {
      url: row.url,
      ...(explicit ?? guess ?? format(kind === "chem-3d" ? "sdf" : "mmcif")),
    }
  }
  if (typeof row.id === "string") return { url: rcsbUrl(row.id), format: "mmcif" }
  if (typeof row.pdbId === "string") return { url: rcsbUrl(row.pdbId), format: "mmcif" }
}

function element(value: string): string | undefined {
  const match = value.trim().match(/^([A-Za-z]{1,2})$/)
  if (!match) return
  return `${match[1]![0]!.toUpperCase()}${match[1]!.slice(1).toLowerCase()}`
}

function countElements(values: Array<string | undefined>): ElementCount[] {
  const counts = values.reduce<Record<string, number>>((all, value) => {
    if (!value) return all
    all[value] = (all[value] ?? 0) + 1
    return all
  }, {})
  return Object.entries(counts)
    .map(([name, count]) => ({ element: name, count }))
    .toSorted((a, b) => b.count - a.count || a.element.localeCompare(b.element))
}

function analyzeXyz(raw: string, source: MolecularSummary["source"]): MolecularSummary {
  const lines = raw.split(/\r?\n/)
  const rows: Array<{ element: string }> = []
  const warnings: string[] = []
  let cursor = 0
  let frames = 0
  while (cursor < lines.length) {
    if (!lines[cursor]?.trim()) { cursor++; continue }
    const header = lines[cursor]!.trim()
    if (!/^\d+$/.test(header)) {
      warnings.push("Invalid XYZ frame atom count.")
      break
    }
    const declared = Number(header)
    const frameRows = lines.slice(cursor + 2, cursor + 2 + declared).flatMap((line) => {
      const parts = line.trim().split(/\s+/)
      const symbol = element(parts[0] ?? "")
      const coordinates = parts.slice(1, 4).map(Number)
      if (!symbol || coordinates.length !== 3 || coordinates.some((value) => !Number.isFinite(value))) return []
      return [{ element: symbol }]
    })
    if (declared !== frameRows.length) warnings.push(`XYZ declares ${declared} atoms but ${frameRows.length} valid coordinate row was parsed.`)
    rows.push(...frameRows)
    frames++
    cursor += declared + 2
  }
  return {
    format: "xyz",
    source,
    atomCount: rows.length,
    moleculeCount: rows.length ? frames : 0,
    elements: countElements(rows.map((row) => row.element)),
    warnings,
  }
}

function pdbElement(line: string): string | undefined {
  const declared = element(line.slice(76, 78))
  if (declared) return declared
  const atom = line.slice(12, 16).trim().replace(/^\d+/, "")
  return element(atom.slice(0, 1))
}

function analyzePdb(raw: string, source: MolecularSummary["source"]): MolecularSummary {
  const lines = raw.split(/\r?\n/)
  const atoms = lines.filter((line) => line.startsWith("ATOM  ") || line.startsWith("HETATM"))
  const chains = new Set(atoms.map((line) => line.slice(21, 22).trim() || "_"))
  const residues = new Set(atoms.map((line) => `${line.slice(21, 22).trim() || "_"}:${line.slice(22, 27).trim()}`))
  const declaredModels = lines.filter((line) => line.startsWith("MODEL ")).length
  return {
    format: "pdb",
    source,
    atomCount: atoms.length,
    chainCount: chains.size,
    residueCount: residues.size,
    modelCount: declaredModels || (atoms.length ? 1 : 0),
    elements: countElements(atoms.map(pdbElement)),
    warnings: [],
  }
}

interface MolRecord {
  atoms: string[]
  atomCount: number
  bondCount: number
}

function molRecord(raw: string): MolRecord | undefined {
  const lines = raw.split(/\r?\n/)
  const index = lines.findIndex((line) => line.includes("V2000"))
  if (index < 0) return
  const counts = lines[index] ?? ""
  const atomCount = Number.parseInt(counts.slice(0, 3).trim(), 10)
  const bondCount = Number.parseInt(counts.slice(3, 6).trim(), 10)
  if (!Number.isFinite(atomCount) || !Number.isFinite(bondCount)) return
  const atoms = lines.slice(index + 1, index + 1 + atomCount).flatMap((line) => {
    const symbol = element(line.slice(31, 34)) ?? element(line.trim().split(/\s+/)[3] ?? "")
    return symbol ? [symbol] : []
  })
  return { atoms, atomCount: atoms.length, bondCount }
}

function analyzeMol(raw: string, source: MolecularSummary["source"], target: "sdf" | "mol"): MolecularSummary {
  const chunks =
    target === "sdf"
      ? raw
          .split(/\$\$\$\$/)
          .map((item) => item.trim())
          .filter(Boolean)
      : [raw]
  const records = chunks.flatMap((chunk) => {
    const value = molRecord(chunk)
    return value ? [value] : []
  })
  const expected = records.reduce((total, record) => total + record.atomCount, 0)
  return {
    format: target,
    source,
    atomCount: expected,
    bondCount: records.reduce((total, record) => total + record.bondCount, 0),
    moleculeCount: records.length,
    elements: countElements(records.flatMap((record) => record.atoms)),
    warnings: records.length ? [] : [`No valid V2000 ${target.toUpperCase()} record was parsed.`],
  }
}

export function analyzeMolecularSource(data: unknown, kind: string): MolecularSummary | undefined {
  const value = narrowMolecularSource(data, kind)
  if (!value) return
  const source: MolecularSummary["source"] = value.raw === undefined ? "remote" : "inline"
  if (source === "remote") {
    return {
      format: value.format,
      source,
      elements: [],
      warnings: ["Scientific properties are available after the remote structure is loaded."],
    }
  }
  const raw = value.raw ?? ""
  if (value.format === "xyz") return analyzeXyz(raw, source)
  if (value.format === "pdb" || value.format === "pdbqt") return analyzePdb(raw, source)
  if (value.format === "sdf") return analyzeMol(raw, source, "sdf")
  if (value.format === "mol") return analyzeMol(raw, source, "mol")
  return {
    format: value.format,
    source,
    elements: [],
    warnings: ["Detailed scientific properties are not available for this format yet."],
  }
}
