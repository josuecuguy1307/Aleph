// Completa en tiempo de arranque la config generada por el pack. La parte sensible
// (base URL y sesión del borde) ya fue escrita por Aleph; este script sólo añade la
// anatomía Legal. Nunca escribe en el árbol importado ni conoce proveedores externos.
import path from "node:path"

const [configFile, root] = process.argv.slice(2)
if (!configFile || !root) throw new Error("uso: aleph-legal-config.ts CONFIG ROOT")
const config = JSON.parse(await Bun.file(configFile).text()) as Record<string, unknown>
const legalRoot = path.join(root, "dochaus")
const plugin = Array.isArray(config.plugin) ? config.plugin : []
config.plugin = [path.join(legalRoot, "plugin", "legal.ts"), ...plugin]
config.skills = { paths: ["{env:WORKSPACE_ROOT}/.playbooks", "{env:WORKSPACE_ROOT}/.skills"] }
config.instructions = [
  "{env:WORKSPACE_ROOT}/.preferences/drafting.md",
  path.join(legalRoot, "instructions", "language.md"),
]
config.disabled_providers = ["opencode"]
config.permission = {
  read: "allow", glob: "allow", grep: "allow", list: "allow", task: "allow",
  skill: { "*": "allow" }, "search-document": "allow", cite: "allow", "case-law": "allow",
  "list-templates": "allow", "get-template": "allow", "update-template": "ask", "delete-template": "ask",
  "list-playbooks": "allow", "update-playbook": "ask", "delete-playbook": "ask",
  "list-workflows": "allow", "create-workflow": "ask", "update-workflow": "ask", "delete-workflow": "ask",
  "list-skills": "allow", "create-skill": "ask", "update-skill": "ask", "delete-skill": "ask",
  "list-agents": "allow", "create-agent": "ask", "update-agent": "ask", "delete-agent": "ask",
  "read-document": "allow", "draft-document": "ask", "create-template": "ask",
  "create-playbook": "ask", "word-integration": "ask", "tracked-changes": "ask",
  redline: "ask", redact: "ask", "redaction-log": "allow", edit: "deny", bash: "deny",
  webfetch: "allow", "web-search": "allow", websearch: "deny",
}
config.agent = { explore: { disable: true }, general: { disable: true }, build: { disable: true }, plan: { disable: true } }
await Bun.write(configFile, JSON.stringify(config, null, 2) + "\n")
