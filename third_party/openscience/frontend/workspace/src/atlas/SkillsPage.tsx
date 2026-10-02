// Skills — the reusable catalog of expert playbooks agents load on demand.
// Data + enable/disable + add flows use the real app.skills / app.skill.write /
// permission.skill APIs. The embedded presentation fits the Customize frame
// without adding a second page title or center-workspace chrome.
import { For, Show, createMemo, createResource, createSignal, type JSX } from "solid-js"
import { Switch } from "@synsci/ui/switch"
import { Icon } from "@synsci/ui/icon"
import { showToast } from "@synsci/ui/toast"
import { useLanguage } from "@/context/language"
import { useGlobalSDK } from "@/context/global-sdk"
import { usePlatform } from "@/context/platform"
import { useGlobalSync } from "@/context/global-sync"
import { FONT_SANS } from "@/styles/tokens"
import type { Config } from "@synsci/sdk/v2/client"
import { installFromGit } from "./skills-settings"
import {
  SearchInput,
  FilterMenu,
  AddMenu,
  Toolbar,
  EmptyState,
  FormField,
  FormButton,
} from "@/components/settings/_shared"

interface Skill {
  name: string
  description?: string
  location: string
  origin?: Source
  category?: string
  tags?: string[]
  entry?: boolean
}

type Action = "allow" | "deny"
type View = "list" | "scratch" | "github"
type Source = "default" | "learned" | "installed" | "user" | "project"
type SourceView = "all" | Source

function sourceOf(skill: Skill): Source {
  if (skill.origin) return skill.origin
  const location = skill.location.toLowerCase()
  if (location.includes("learned-skills")) return "learned"
  if (location.includes("installed-skills") || location.includes(".claude/skills")) return "installed"
  if (location.includes("user-skills")) return "user"
  if (location.includes(".openscience/")) return "project"
  return "default"
}

const SOURCE_DOT: Record<Source, string> = {
  default: "var(--color-text-faint)",
  learned: "var(--color-success, #26734e)",
  installed: "var(--color-text-interactive-base, var(--color-text))",
  user: "var(--color-warning, #8a5d0c)",
  project: "var(--color-info, #366d84)",
}


export default function SkillsPage(props: { embedded?: boolean }): JSX.Element {
  const language = useLanguage()
  const sdk = useGlobalSDK()
  const platform = usePlatform()
  const sync = useGlobalSync()

  const [skills, skillsCtl] = createResource(async () => {
    const res = await sdk.client.app.skills()
    return (res.data ?? []) as Skill[]
  })

  const [search, setSearch] = createSignal("")
  const [category, setCategory] = createSignal("all")
  const [source, setSource] = createSignal<SourceView>("all")
  const [view, setView] = createSignal<View>("list")
  const [busy, setBusy] = createSignal(false)
  let fileInput: HTMLInputElement | undefined

  // Enable/disable is the real `permission.skill` config: a skill an agent can
  // load is one whose skill-permission isn't "deny" (the skill tool filters the
  // rest), so this toggle is effective, not cosmetic.
  const skillPerm = createMemo<Record<string, Action>>(() => {
    const perm = sync.data.config.permission
    if (!perm || typeof perm === "string") return {}
    const skill = (perm as Record<string, unknown>).skill
    if (!skill || typeof skill === "string") return {}
    return skill as Record<string, Action>
  })
  const enabled = (name: string) => skillPerm()[name] !== "deny"

  async function toggle(name: string, next: boolean) {
    const map: Record<string, Action> = { ...skillPerm(), [name]: next ? "allow" : "deny" }
    const perm = sync.data.config.permission
    const base = perm && typeof perm === "object" ? perm : {}
    sync.set("config", "permission", { ...base, skill: map })
    try {
      await sync.updateConfig({ permission: { skill: map } } as Config)
    } catch (err) {
      showToast({ variant: "error", title: language.t("settings.skillsOwned.text1"), description: message(err) })
    }
  }

  const all = () => skills() ?? []
  const enabledCount = createMemo(() => all().filter((s) => enabled(s.name)).length)

  const categories = createMemo(() => {
    const counts = new Map<string, number>()
    for (const s of all()) {
      const cat = s.category ?? "uncategorized"
      counts.set(cat, (counts.get(cat) ?? 0) + 1)
    }
    return [
      { id: "all", label: language.t("settings.skillsOwned.text2"), count: all().length },
      ...[...counts.entries()]
        .sort((a, b) => a[0].localeCompare(b[0]))
        .map(([id, count]) => ({ id, label: id === "uncategorized" ? language.t("settings.skillsOwned.uncategorized") : id, count })),
    ]
  })

  const sources = createMemo(() => {
    const count = (value: Source) => all().filter((skill) => sourceOf(skill) === value).length
    return [
      { id: "all", label: language.t("settings.skillsOwned.text3"), count: all().length },
      { id: "default", label: language.t("settings.skillsOwned.text4"), count: count("default") },
      { id: "installed", label: language.t("settings.skillsOwned.text6"), count: count("installed") },
      { id: "learned", label: language.t("settings.skillsOwned.text5"), count: count("learned") },
      { id: "user", label: language.t("settings.skillsOwned.text7"), count: count("user") },
      { id: "project", label: language.t("settings.skillsOwned.text8"), count: count("project") },
    ]
  })

  const filtered = createMemo(() => {
    const q = search().trim().toLowerCase()
    const cat = category()
    const origin = source()
    return all()
      .filter((skill) => origin === "all" || sourceOf(skill) === origin)
      .filter((s) => cat === "all" || (s.category ?? "uncategorized") === cat)
      .filter((s) => !q || s.name.toLowerCase().includes(q) || (s.description ?? "").toLowerCase().includes(q))
      .sort((a, b) => a.name.localeCompare(b.name))
  })

  // Group the filtered set into category shelves, sorted by name.
  const shelves = createMemo(() => {
    const by = new Map<string, Skill[]>()
    for (const s of filtered()) {
      const cat = s.category ?? "uncategorized"
      if (!by.has(cat)) by.set(cat, [])
      by.get(cat)!.push(s)
    }
    return [...by.entries()].sort((a, b) => a[0].localeCompare(b[0]))
  })

  return (
    <div class="skills-workspace" data-layout={props.embedded ? "settings" : "workspace"}>
      <div class="skills-workspace__header">
        <Show when={!props.embedded}>
          <div class="skills-workspace__heading">
            <div>
              <h1>Skills</h1>
              <p>{language.t("settings.skillsOwned.text9")}</p>
            </div>
            <div class="skills-workspace__summary">
              <span>{language.t("settings.skillsOwned.enabled", { count: enabledCount() })}</span>
              <span>{language.t("settings.skillsOwned.total", { count: all().length })}</span>
            </div>
          </div>
        </Show>
        <Show when={props.embedded}>
          <div class="skills-workspace__summary">
            <span>{language.t("settings.skillsOwned.enabled", { count: enabledCount() })}</span>
            <span>{language.t("settings.skillsOwned.total", { count: all().length })}</span>
          </div>
        </Show>

        <Show when={view() === "list"}>
          <div class="skills-workspace__toolbar">
            <Toolbar>
              <FilterMenu options={sources()} value={source()} onSelect={(value) => setSource(value as SourceView)} />
              <FilterMenu options={categories()} value={category()} onSelect={setCategory} />
              <SearchInput value={search()} onInput={setSearch} placeholder={language.t("settings.skillsOwned.text10")} />
              <AddMenu
                label={language.t("settings.skillsOwned.text11")}
                items={[
                  {
                    icon: "pencil-line",
                    label: language.t("settings.skillsOwned.text12"),
                    description: language.t("settings.skillsOwned.text13"),
                    onSelect: () => setView("scratch"),
                  },
                  {
                    icon: "cloud-upload",
                    label: language.t("settings.skillsOwned.text14"),
                    description: language.t("settings.skillsOwned.text15"),
                    onSelect: () => fileInput?.click(),
                  },
                  {
                    icon: "github",
                    label: language.t("settings.skillsOwned.text16"),
                    description: language.t("settings.skillsOwned.text17"),
                    onSelect: () => setView("github"),
                  },
                ]}
              />
            </Toolbar>
          </div>
        </Show>
      </div>

      <input
        ref={fileInput}
        type="file"
        accept=".md,text/markdown"
        class="hidden"
        onChange={(e) => {
          const file = e.currentTarget.files?.[0]
          e.currentTarget.value = ""
          if (file) void uploadSkill(file)
        }}
      />

      <div class="atlas-scroll skills-workspace__body">
        <div class="skills-workspace__content">
          <Show when={view() === "scratch"}>
            <ScratchForm
              busy={busy()}
              onCancel={() => setView("list")}
              onCreate={async (name, description, body) => {
                setBusy(true)
                try {
                  const content = `---\nname: ${name}\ndescription: ${description}\n---\n\n${body}\n`
                  await sdk.client.app.skill.write({ name, content })
                  await skillsCtl.refetch()
                  showToast({ variant: "success", title: language.t("settings.skillsOwned.created", { name }) })
                  setView("list")
                } catch (err) {
                  showToast({ variant: "error", title: language.t("settings.skillsOwned.text18"), description: message(err) })
                } finally {
                  setBusy(false)
                }
              }}
            />
          </Show>

          <Show when={view() === "github"}>
            <GithubForm
              busy={busy()}
              onCancel={() => setView("list")}
              onInstall={async (url) => {
                setBusy(true)
                try {
                  const res = await installFromGit(platform.fetch ?? fetch, sdk.url, url)
                  await skillsCtl.refetch()
                  const n = res.installed.length
                  const r = res.rejected.length
                  showToast({
                    variant: n > 0 ? "success" : "error",
                    title: n > 0 ? language.t("settings.skillsOwned.installed", { count: n }) : language.t("settings.skillsOwned.text19"),
                    description: r > 0 ? language.t("settings.skillsOwned.rejected", { count: r }) : undefined,
                  })
                  if (n > 0) setView("list")
                } catch (err) {
                  showToast({ variant: "error", title: language.t("settings.skillsOwned.text20"), description: message(err) })
                } finally {
                  setBusy(false)
                }
              }}
            />
          </Show>

          <Show when={view() === "list"}>
            <Show when={!skills.loading} fallback={<div style={loadingStyle()}>{language.t("settings.skillsOwned.text21")}</div>}>
              <Show
                when={filtered().length > 0}
                fallback={
                  <div style={{ "padding-top": "36px" }}>
                    <EmptyState
                      icon="brain"
                      title={
                        search() || category() !== "all" || source() !== "all" ? language.t("settings.skillsOwned.text22") : language.t("settings.skillsOwned.text23")
                      }
                      hint={language.t("settings.skillsOwned.text24")}
                    />
                  </div>
                }
              >
                <div class="skills-workspace__list">
                  <For each={shelves()}>
                    {([cat, items]) => (
                      <section class="skills-workspace__group">
                        <div class="skills-workspace__group-heading">
                          <span class="atlas-section-label">{cat === "uncategorized" ? language.t("settings.skillsOwned.uncategorized") : cat}</span>
                          <span>{items.length}</span>
                        </div>
                        <div class="skills-workspace__rows">
                          <For each={items}>
                            {(skill) => (
                              <SkillRow
                                skill={skill}
                                on={enabled(skill.name)}
                                onToggle={(v) => void toggle(skill.name, v)}
                              />
                            )}
                          </For>
                        </div>
                      </section>
                    )}
                  </For>
                </div>
              </Show>
            </Show>
          </Show>
        </div>
      </div>
    </div>
  )

  async function uploadSkill(file: File) {
    setBusy(true)
    try {
      const content = await file.text()
      const name = frontmatterName(content) ?? file.name.replace(/\.md$/i, "")
      if (!frontmatterName(content)) {
        throw new Error(language.t("settings.skillsOwned.text25"))
      }
      await sdk.client.app.skill.write({ name, content })
      await skillsCtl.refetch()
      showToast({ variant: "success", title: language.t("settings.skillsOwned.uploaded", { name }) })
    } catch (err) {
      showToast({ variant: "error", title: language.t("settings.skillsOwned.text26"), description: message(err) })
    } finally {
      setBusy(false)
    }
  }
}

function SkillRow(props: { skill: Skill; on: boolean; onToggle: (v: boolean) => void }): JSX.Element {
  const language = useLanguage()
  const source = () => sourceOf(props.skill)
  return (
    <div class="skills-workspace__row" data-enabled={props.on ? "true" : "false"}>
      <div class="skills-workspace__identity">
        <strong title={props.skill.name}>{props.skill.name}</strong>
        <span>
          <i style={{ background: SOURCE_DOT[source()] }} />
          {language.t(`settings.skillsOwned.source.${source()}`)}
        </span>
      </div>

      <Show when={props.skill.description}>
        <p>{props.skill.description}</p>
      </Show>

      <div class="skills-workspace__tags">
        <For each={(props.skill.tags ?? []).slice(0, 3)}>{(tag) => <span>{tag}</span>}</For>
      </div>
      <Switch data-action="skill-toggle" checked={props.on} onChange={props.onToggle} hideLabel>
        {props.skill.name}
      </Switch>
    </div>
  )
}

function ScratchForm(props: {
  busy: boolean
  onCancel: () => void
  onCreate: (name: string, description: string, body: string) => void
}): JSX.Element {
  const language = useLanguage()
  const [name, setName] = createSignal("")
  const [description, setDescription] = createSignal("")
  const [body, setBody] = createSignal("")
  const valid = () => /^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$/.test(name().trim()) && description().trim().length > 0
  return (
    <div class="flex flex-col gap-4 max-w-[680px]">
      <span class="atlas-section-label">{language.t("settings.skillsOwned.text27")}</span>
      <div class="flex flex-col gap-4 p-5 border border-border-weak-base rounded-[8px] bg-surface-base/40">
        <FormField label={language.t("settings.skillsOwned.text28")} value={name()} onInput={setName} placeholder={language.t("settings.skillsOwned.text29")} />
        <FormField
          label={language.t("settings.skillsOwned.text30")}
          value={description()}
          onInput={setDescription}
          placeholder={language.t("settings.skillsOwned.text31")}
        />
        <FormField
          label={language.t("settings.skillsOwned.text32")}
          value={body()}
          onInput={setBody}
          multiline
          mono
          placeholder={language.t("settings.skillsOwned.text33")}
        />
        <div class="flex items-center gap-2">
          <FormButton
            label={props.busy ? language.t("settings.skillsOwned.text34") : language.t("settings.skillsOwned.text35")}
            disabled={props.busy || !valid()}
            onClick={() => props.onCreate(name().trim(), description().trim(), body())}
          />
          <FormButton label={language.t("settings.skillsOwned.text36")} variant="ghost" onClick={props.onCancel} disabled={props.busy} />
        </div>
      </div>
    </div>
  )
}

function GithubForm(props: { busy: boolean; onCancel: () => void; onInstall: (url: string) => void }): JSX.Element {
  const language = useLanguage()
  const [url, setUrl] = createSignal("")
  return (
    <div class="flex flex-col gap-4 max-w-[680px]">
      <span class="atlas-section-label">{language.t("settings.skillsOwned.text16")}</span>
      <div class="flex flex-col gap-4 p-5 border border-border-weak-base rounded-[8px] bg-surface-base/40">
        <FormField label={language.t("settings.skillsOwned.text37")} value={url()} onInput={setUrl} placeholder="https://github.com/owner/repo" />
        <p class="text-12-regular text-text-weak flex items-start gap-1.5">
          <Icon name="check-small" size="small" class="text-icon-weak-base mt-0.5" />
          {language.t("settings.skillsOwned.text38")}
        </p>
        <div class="flex items-center gap-2">
          <FormButton
            label={props.busy ? language.t("settings.skillsOwned.text39") : language.t("settings.skillsOwned.text40")}
            disabled={props.busy || !url().trim()}
            onClick={() => props.onInstall(url().trim())}
          />
          <FormButton label={language.t("settings.skillsOwned.text36")} variant="ghost" onClick={props.onCancel} disabled={props.busy} />
        </div>
      </div>
    </div>
  )
}

function loadingStyle(): JSX.CSSProperties {
  return {
    padding: "48px 0",
    "text-align": "center",
    "font-family": FONT_SANS,
    "font-size": "13px",
    color: "var(--color-text-muted)",
  }
}

function frontmatterName(content: string): string | undefined {
  const match = content.match(/^---\s*[\r\n]([\s\S]*?)[\r\n]---/)
  if (!match) return undefined
  const line = match[1].split(/\r?\n/).find((l) => /^name\s*:/.test(l))
  return line
    ?.split(":")
    .slice(1)
    .join(":")
    .trim()
    .replace(/^["']|["']$/g, "")
}

function message(err: unknown) {
  return err instanceof Error ? err.message : String(err)
}
