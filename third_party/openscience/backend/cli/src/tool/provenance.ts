import z from "zod"
import { Tool } from "./tool"
import { Provenance } from "../science/provenance/store"
import { Review } from "../science/provenance/review"
import { Instance } from "../project/instance"

/**
 * Agent-facing tools over the provenance DAG. Let the model record what it
 * produced and audit the lineage of any artifact/claim later.
 */

const scope = () => ({
  projectID: Instance.project.id,
  directory: Instance.directory,
})

export const ProvenanceRecordTool = Tool.define("provenance_record", {
  description: [
    "Record a node (and optional edge) in the provenance DAG.",
    "Use to log artifacts you produce (datasets, figures, models, reports) and the runs that made them.",
    "Nodes are content-addressed; recording identical content returns the same id.",
  ].join("\n"),
  parameters: z.object({
    kind: z.enum(["artifact", "run", "source", "claim"]).describe("Node kind"),
    label: z.string().describe("Human-readable label"),
    artifact_type: z
      .string()
      .optional()
      .describe("For artifact nodes: type e.g. 'dataset' | 'figure' | 'model' | 'report'"),
    path: z.string().optional().describe("On-disk path if the node is a materialized file"),
    tool: z.string().optional().describe("For run nodes: the tool/command that executed"),
    meta: z.record(z.string(), z.any()).optional().describe("Arbitrary structured metadata"),
    derived_from: z
      .string()
      .optional()
      .describe("Optional id of a parent node this was derived from (creates a 'derived-from' edge)"),
  }),
  async execute(params, ctx) {
    if (params.derived_from) {
      const graph = await Provenance.project(scope())
      if (!graph.nodes.some((node) => node.id === params.derived_from)) {
        throw new Error(`Provenance node ${params.derived_from} is not part of this project`)
      }
    }
    const node = await Provenance.recordOwned(scope(), {
      kind: params.kind,
      label: params.label,
      ...(params.artifact_type ? { artifactType: params.artifact_type } : {}),
      ...(params.path ? { path: params.path } : {}),
      ...(params.tool ? { tool: params.tool } : {}),
      meta: {
        ...params.meta,
        sessionID: ctx.sessionID,
        directory: Instance.directory,
        projectID: Instance.project.id,
      },
    } as Parameters<typeof Provenance.record>[0])

    if (params.derived_from) {
      await Provenance.linkOwned(scope(), { from: node.id, to: params.derived_from, relation: "derived-from" })
    }

    return {
      title: `Recorded ${params.kind}: ${node.id}`,
      output: [
        `Recorded provenance node.`,
        `  id: ${node.id}`,
        `  kind: ${node.kind}`,
        `  label: ${node.label}`,
        params.derived_from ? `  derived-from: ${params.derived_from}` : "",
      ]
        .filter(Boolean)
        .join("\n"),
      metadata: { id: node.id, kind: node.kind },
    }
  },
})

export const ProvenanceQueryTool = Tool.define("provenance_query", {
  description: [
    "Query the provenance DAG. With `id`, returns that node plus its lineage tree.",
    "Without `id`, lists all recorded nodes. Use to audit how an artifact or claim was produced.",
  ].join("\n"),
  parameters: z.object({
    id: z.string().optional().describe("Node id to trace lineage for. Omit to list everything."),
  }),
  async execute(params, _ctx) {
    const graph = await Provenance.project(scope())
    if (!params.id) {
      const nodes = graph.nodes
      if (!nodes.length) {
        return { title: "Provenance", output: "No provenance nodes recorded yet.", metadata: { count: 0, edges: 0 } }
      }
      const rows = nodes.map((n) => `- **${n.id}** [${n.kind}] ${n.label}`)
      return {
        title: `Provenance (${nodes.length} nodes)`,
        output: rows.join("\n"),
        metadata: { count: nodes.length, edges: 0 },
      }
    }

    if (!graph.nodes.some((node) => node.id === params.id)) {
      return { title: "Provenance", output: `No node "${params.id}".`, metadata: { count: 0, edges: 0 } }
    }
    const connected = new Set([params.id])
    const queue = [params.id]
    while (queue.length) {
      const current = queue.shift()!
      for (const edge of graph.edges) {
        if (edge.from !== current && edge.to !== current) continue
        const next = edge.from === current ? edge.to : edge.from
        if (connected.has(next)) continue
        connected.add(next)
        queue.push(next)
      }
    }
    const nodes = graph.nodes.filter((node) => connected.has(node.id))
    const edges = graph.edges.filter((edge) => connected.has(edge.from) && connected.has(edge.to))
    const nodeRows = nodes.map((n) => `- **${n.id}** [${n.kind}] ${n.label}`)
    const edgeRows = edges.map((e) => `- ${e.from} --${e.relation}--> ${e.to}`)
    return {
      title: `Lineage: ${params.id}`,
      output: [
        `**Nodes** (${nodes.length}):`,
        nodeRows.join("\n"),
        "",
        `**Edges** (${edges.length}):`,
        edgeRows.join("\n"),
      ].join("\n"),
      metadata: { count: nodes.length, edges: edges.length },
    }
  },
})

export const ProvenanceReviewTool = Tool.define("provenance_review", {
  description: [
    "Record a reviewer finding against a provenance node.",
    "Use to flag a claim, statistic, or figure that the evidence does not support (verdict 'refutes'),",
    "or to log a check that passed sound (verdict 'supports').",
    "Creates a content-addressed 'claim' node holding {claim, issue, severity, evidence} and links it",
    "to the target node with a 'refutes'/'supports' edge. Append-only audit trail — the artifact is not modified.",
  ].join("\n"),
  parameters: z.object({
    target: z
      .string()
      .describe("Provenance node id the finding is about (the claim / artifact / figure / run under review)"),
    claim: z.string().describe("The exact claim, number, or figure being evaluated (quote it)"),
    issue: z.string().describe("What is wrong with it — or 'verified' when the finding supports it"),
    severity: z
      .enum(["blocking", "major", "minor", "info"])
      .describe("Severity: blocking (invalidates a headline claim) | major | minor | info"),
    evidence: z
      .string()
      .describe("Concrete evidence: file:line, value, tool-output id, or provenance node id proving the finding"),
    verdict: z
      .enum(["refutes", "supports"])
      .default("refutes")
      .describe("'refutes' flags a defect (default); 'supports' records a verified-sound check"),
  }),
  async execute(params, ctx) {
    const graph = await Provenance.project(scope())
    if (!graph.nodes.some((node) => node.id === params.target)) {
      throw new Error(`Provenance node ${params.target} is not part of this project`)
    }
    const { node, relation } = await Review.record({
      target: params.target,
      finding: {
        claim: params.claim,
        issue: params.issue,
        severity: params.severity,
        evidence: params.evidence,
      },
      verdict: params.verdict,
      reviewer: ctx.agent,
      sessionID: ctx.sessionID,
      messageID: ctx.messageID,
      callID: ctx.callID,
      projectID: Instance.project.id,
      directory: Instance.directory,
    })
    return {
      title: `Review ${relation}: ${node.id}`,
      output: [
        `Recorded reviewer finding.`,
        `  finding id: ${node.id}`,
        `  target:     ${params.target}`,
        `  relation:   ${node.id} --${relation}--> ${params.target}`,
        `  severity:   ${params.severity}`,
        `  claim:      ${params.claim}`,
        `  issue:      ${params.issue}`,
        `  evidence:   ${params.evidence}`,
      ].join("\n"),
      metadata: { id: node.id, target: params.target, relation, severity: params.severity },
    }
  },
})

export const ProvenanceTools = [ProvenanceRecordTool, ProvenanceQueryTool, ProvenanceReviewTool]

export const PROVENANCE_TOOL_IDS = new Set(["provenance_record", "provenance_query", "provenance_review"])
