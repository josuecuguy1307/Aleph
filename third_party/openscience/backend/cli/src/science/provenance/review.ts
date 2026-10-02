/**
 * Reviewer findings over the provenance DAG.
 *
 * The reviewer sub-agent (actor-critic critic half) audits research outputs and
 * flags claims that the evidence does not support. A finding is recorded as a
 * content-addressed `claim` node holding {claim, issue, severity, evidence} and
 * linked to the node it concerns with a `refutes` edge (a defect) or a `supports`
 * edge (a check that passed). This is an append-only audit trail — it annotates
 * lineage, it never mutates the reviewed artifact.
 */
import { Provenance, type Node, type Edge, type ProjectScope } from "./store"

/** Severity of a reviewer finding. Mirrors the reviewer prompt's vocabulary. */
export type Severity = "blocking" | "major" | "minor" | "info"

/** A structured reviewer finding: {claim, issue, severity, evidence}. */
export interface Finding {
  /** The exact claim, number, or figure under review. */
  claim: string
  /** What is wrong with it (or "verified" when the finding supports it). */
  issue: string
  /** How serious the defect is. */
  severity: Severity
  /** Concrete evidence: file:line, value, tool-output id, or provenance node id. */
  evidence: string
}

export interface ReviewResult {
  /** The recorded finding node. */
  node: Node
  /** The relation used to link the finding to the target. */
  relation: "refutes" | "supports"
}

export namespace Review {
  /**
   * Record a reviewer finding against an existing provenance node.
   *
   * Creates a `claim` node carrying the finding payload and links it to `target`
   * with `refutes` (default — a defect was found) or `supports` (a verified-sound
   * check). The finding node is content-addressed, so identical findings dedupe.
   */
  export async function record(input: {
    /** Provenance node id the finding is about (claim / artifact / figure / run). */
    target: string
    finding: Finding
    /** "refutes" flags a problem (default); "supports" records a verified-sound check. */
    verdict?: "refutes" | "supports"
    /** Who recorded it (agent name). */
    reviewer?: string
    sessionID?: string
    /** Exact message (and tool call) that produced the finding, when known. */
    messageID?: string
    callID?: string
    projectID: string
    directory: string
  }): Promise<ReviewResult> {
    const relation = input.verdict ?? "refutes"
    if (!(await Provenance.find(input, input.target))) {
      throw new Error(`Provenance node ${input.target} is not part of this project`)
    }
    const node = await Provenance.recordOwned(input, {
      kind: "claim",
      label: `review (${input.finding.severity}): ${input.finding.issue}`.slice(0, 140),
      meta: {
        review: true,
        target: input.target,
        claim: input.finding.claim,
        issue: input.finding.issue,
        severity: input.finding.severity,
        evidence: input.finding.evidence,
        verdict: relation,
        reviewer: input.reviewer ?? "reviewer",
        sessionID: input.sessionID,
        ...(input.messageID !== undefined ? { messageID: input.messageID } : {}),
        ...(input.callID !== undefined ? { callID: input.callID } : {}),
        directory: input.directory,
        projectID: input.projectID,
      },
    })
    await Provenance.linkOwned(input, { from: node.id, to: input.target, relation })
    return { node, relation }
  }

  /**
   * All reviewer findings recorded against a node — the incoming `supports` /
   * `refutes` edges from review claim-nodes. Use to audit what has been flagged.
   */
  export async function forNode(
    input: ProjectScope,
    target: string,
  ): Promise<Array<{ finding: Node; relation: Edge["relation"] }>> {
    const { nodes, edges } = await Provenance.query(input, target)
    const byId = new Map(nodes.map((n) => [n.id, n]))
    return edges
      .filter((e) => e.to === target && (e.relation === "refutes" || e.relation === "supports"))
      .map((e) => ({ finding: byId.get(e.from), relation: e.relation }))
      .filter(
        (r): r is { finding: Node; relation: Edge["relation"] } =>
          Boolean(r.finding) && (r.finding!.meta as Record<string, unknown> | undefined)?.review === true,
      )
  }

  /** Lifecycle of a refuting finding, derived from the append-only trail:
   *  "open" until someone records a fix, "addressed" once they have, and
   *  "confirmed" only after a LATER reviewer pass records a supports finding
   *  on the same target — a fix is never closed by assertion alone. */
  export type Status = "open" | "addressed" | "confirmed"

  export interface Entry {
    finding: Node
    target: string
    verdict: "refutes" | "supports"
    status?: Status
    resolution?: { actor: string; reason: string; recordedAt: string }
  }

  /** Record that a refuting finding was addressed. Append-only: this adds a
   *  resolution node linked to the finding; it never rewrites the finding. */
  export async function resolve(input: {
    finding: string
    actor: string
    reason: string
    projectID: string
    directory: string
    sessionID?: string
  }): Promise<Node> {
    const finding = await Provenance.find(input, input.finding)
    const meta = finding?.meta as Record<string, unknown> | undefined
    if (!finding || meta?.review !== true) {
      throw new Error(`Provenance node ${input.finding} is not a reviewer finding in this project`)
    }
    if (meta.verdict !== "refutes") {
      throw new Error(`Finding ${input.finding} records a passed check — there is nothing to address`)
    }
    const node = await Provenance.recordOwned(input, {
      kind: "claim",
      label: `resolution: ${input.reason}`.slice(0, 140),
      meta: {
        resolution: true,
        finding: input.finding,
        actor: input.actor,
        reason: input.reason,
        sessionID: input.sessionID,
        directory: input.directory,
        projectID: input.projectID,
      },
    })
    await Provenance.linkOwned(input, { from: node.id, to: input.finding, relation: "supports" })
    return node
  }

  /** Every reviewer finding in the project with its derived lifecycle status. */
  export async function list(input: ProjectScope): Promise<Entry[]> {
    const graph = await Provenance.project(input)
    const meta = (node: Node) => (node.meta ?? {}) as Record<string, unknown>
    const findings = graph.nodes.filter((node) => meta(node).review === true)
    const resolutions = graph.nodes.filter((node) => meta(node).resolution === true)

    return findings.map((finding) => {
      const detail = meta(finding)
      const target = typeof detail.target === "string" ? detail.target : ""
      const verdict = detail.verdict === "supports" ? ("supports" as const) : ("refutes" as const)
      if (verdict === "supports") return { finding, target, verdict }

      const resolution = resolutions
        .filter((node) => meta(node).finding === finding.id)
        .toSorted((a, b) => b.recordedAt.localeCompare(a.recordedAt))[0]
      if (!resolution) return { finding, target, verdict, status: "open" as const }

      const confirmed = findings.some(
        (other) =>
          meta(other).target === target &&
          meta(other).verdict === "supports" &&
          other.recordedAt > resolution.recordedAt,
      )
      const detailed = meta(resolution)
      return {
        finding,
        target,
        verdict,
        status: confirmed ? ("confirmed" as const) : ("addressed" as const),
        resolution: {
          actor: typeof detailed.actor === "string" ? detailed.actor : "unknown",
          reason: typeof detailed.reason === "string" ? detailed.reason : "",
          recordedAt: resolution.recordedAt,
        },
      }
    })
  }
}
