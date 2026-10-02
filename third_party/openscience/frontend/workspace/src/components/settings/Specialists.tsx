import { For, Show, createMemo, createResource, createSignal } from "solid-js"
import { IconButton } from "@synsci/ui/icon-button"
import { Switch } from "@synsci/ui/switch"
import { showToast } from "@synsci/ui/toast"
import { useLanguage } from "@/context/language"
import { useGlobalSDK } from "@/context/global-sdk"
import { useGlobalSync } from "@/context/global-sync"
import { usePlatform } from "@/context/platform"
import type { Agent, Config } from "@synsci/sdk/v2/client"
import { settingsApi } from "./api"
import {
  PanelScroll,
  PanelHeader,
  PanelBody,
  Toolbar,
  SearchInput,
  FilterMenu,
  AddMenu,
  Card,
  Row,
  SectionLabel,
  EmptyState,
  FormField,
  FormButton,
  Avatar,
  Chip,
} from "./_shared"
import { isVisibleSpecialist } from "./specialist-catalog"

const LABELS = {"research":"settings.specialistsOwned.label.research","ml":"settings.specialistsOwned.label.ml","biology":"settings.specialistsOwned.label.biology","physics":"settings.specialistsOwned.label.physics","write":"settings.specialistsOwned.label.write","docs":"settings.specialistsOwned.label.docs","task":"settings.specialistsOwned.label.task","explore":"settings.specialistsOwned.label.explore","literature-review":"settings.specialistsOwned.label.literature-review","critique":"settings.specialistsOwned.label.critique","physics-critique":"settings.specialistsOwned.label.physics-critique","reviewer":"settings.specialistsOwned.label.reviewer"} as const

type Mode = "primary" | "subagent" | "all"
type ReviewPreferences = {
  auto: boolean
  model: { providerID: string; modelID: string } | null
}

export default function Specialists() {
  const language = useLanguage()
  const sdk = useGlobalSDK()
  const globalSDK = useGlobalSDK()
  const sync = useGlobalSync()
  const platform = usePlatform()

  // Reviewer preference — GET/PUT /settings/review (backend/cli/src/settings/
  // review.ts). Manual review stays always available from the session header;
  // this only opts into an automatic pass after a durable artifact save.
  const fetchFn = platform.fetch ?? fetch
  const reviewApi = (init?: RequestInit) => settingsApi<ReviewPreferences>(sdk.url, fetchFn, "/settings/review", init)
  const [reviewPrefs, reviewCtl] = createResource(() => reviewApi())
  const [reviewSaving, setReviewSaving] = createSignal(false)
  async function toggleAutoReview(auto: boolean) {
    setReviewSaving(true)
    try {
      reviewCtl.mutate(
        await reviewApi({
          method: "PUT",
          body: JSON.stringify({ auto, model: reviewPrefs()?.model ?? null }),
        }),
      )
    } catch (err) {
      showToast({ variant: "error", title: language.t("settings.specialistsOwned.updateFailed"), description: message(err) })
    } finally {
      setReviewSaving(false)
    }
  }

  const [agents, agentsCtl] = createResource(async () => {
    const res = await sdk.client.app.agents()
    // This screen is the catalog, so show every real non-hidden specialist,
    // including built-in subagents. Planning remains adaptive in Research and
    // the title/compaction implementation agents stay out of product UI.
    return ((res.data ?? []) as Agent[]).filter(isVisibleSpecialist)
  })

  const [search, setSearch] = createSignal("")
  const [modeFilter, setModeFilter] = createSignal("all")
  const [creating, setCreating] = createSignal(false)
  const [busy, setBusy] = createSignal(false)

  const visible = createMemo(() => {
    const q = search().trim().toLowerCase()
    const m = modeFilter()
    return (agents() ?? [])
      .filter((a) => m === "all" || a.mode === m || (m === "primary" && a.mode === "all"))
      .filter((a) => !q || a.name.toLowerCase().includes(q) || (a.description ?? "").toLowerCase().includes(q))
  })
  const builtIn = createMemo(() =>
    visible()
      .filter((a) => a.native)
      .sort(byName),
  )
  const custom = createMemo(() =>
    visible()
      .filter((a) => !a.native)
      .sort(byName),
  )

  const modeOptions = createMemo(() => [
    { id: "all", label: language.t("settings.specialistsOwned.all"), count: (agents() ?? []).length },
    {
      id: "primary",
      label: language.t("settings.specialistsOwned.primary"),
      count: (agents() ?? []).filter((a) => a.mode === "primary" || a.mode === "all").length,
    },
    { id: "subagent", label: language.t("settings.specialistsOwned.subagents"), count: (agents() ?? []).filter((a) => a.mode === "subagent").length },
  ])

  async function createAgent(name: string, description: string, prompt: string, mode: Mode) {
    setBusy(true)
    try {
      const agent: Config["agent"] = { [name]: { description, prompt: prompt || undefined, mode } }
      await sync.updateConfig({ agent } as Config)
      await agentsCtl.refetch()
      showToast({ variant: "success", title: language.t("settings.specialistsOwned.created", { name }) })
      setCreating(false)
    } catch (err) {
      showToast({ variant: "error", title: language.t("settings.specialistsOwned.createFailed"), description: message(err) })
    } finally {
      setBusy(false)
    }
  }

  async function deleteAgent(name: string) {
    if (!window.confirm(language.t("settings.specialistsOwned.confirmDelete", { name }))) return
    setBusy(true)
    try {
      await globalSDK.client.global.configUnset({ path: ["agent", name] })
      await agentsCtl.refetch()
      showToast({ variant: "success", title: language.t("settings.specialistsOwned.deleted", { name }) })
    } catch (err) {
      showToast({ variant: "error", title: language.t("settings.specialistsOwned.deleteFailed"), description: message(err) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <PanelScroll>
      <PanelHeader
        title={language.t("settings.shell.specialists")}
        description={language.t("settings.specialistsOwned.description")}
        toolbar={
          <Show when={!creating()}>
            <Toolbar>
              <FilterMenu options={modeOptions()} value={modeFilter()} onSelect={setModeFilter} />
              <SearchInput value={search()} onInput={setSearch} placeholder={language.t("settings.specialistsOwned.search")} />
              <AddMenu
                label={language.t("settings.specialistsOwned.add")}
                items={[
                  {
                    icon: "pencil-line",
                    label: language.t("settings.specialistsOwned.scratch"),
                    description: language.t("settings.specialistsOwned.scratchHelp"),
                    onSelect: () => setCreating(true),
                  },
                ]}
              />
            </Toolbar>
          </Show>
        }
      />

      <PanelBody>
        <Show when={creating()}>
          <CreateForm busy={busy()} onCancel={() => setCreating(false)} onCreate={createAgent} />
        </Show>

        <Show when={!creating()}>
          <div class="flex flex-col gap-2">
            <SectionLabel label={language.t("settings.specialistsOwned.reviewer")} />
            <Card>
              <Row>
                <div class="min-w-0 flex-1">
                  <span class="text-14-medium text-text-strong">{language.t("settings.specialistsOwned.auto")}</span>
                  <p class="text-12-regular text-text-weak mt-0.5">
                    {language.t("settings.specialistsOwned.autoHelp")}
                  </p>
                </div>
                <Switch
                  hideLabel
                  checked={reviewPrefs()?.auto ?? false}
                  disabled={reviewSaving() || reviewPrefs.loading}
                  onChange={(auto) => void toggleAutoReview(auto)}
                >
                  {language.t("settings.specialistsOwned.auto")}
                </Switch>
              </Row>
            </Card>
          </div>

          <Show
            when={!agents.loading}
            fallback={<div class="py-12 text-center text-13-regular text-text-weak">{language.t("settings.specialistsOwned.loading")}</div>}
          >
            <Show
              when={visible().length > 0}
              fallback={
                <EmptyState
                  icon="models"
                  title={search() ? language.t("settings.specialistsOwned.noMatch") : language.t("settings.specialistsOwned.empty")}
                  hint={language.t("settings.specialistsOwned.emptyHelp")}
                />
              }
            >
              <Show when={custom().length > 0}>
                <div class="flex flex-col gap-2">
                  <SectionLabel label={language.t("settings.specialistsOwned.custom")} count={custom().length} />
                  <Card>
                    <For each={custom()}>
                      {(agent) => (
                        <AgentRow agent={agent} onDelete={() => void deleteAgent(agent.name)} busy={busy()} />
                      )}
                    </For>
                  </Card>
                </div>
              </Show>

              <Show when={builtIn().length > 0}>
                <div class="flex flex-col gap-2">
                  <SectionLabel label={language.t("settings.specialistsOwned.builtIn")} count={builtIn().length} />
                  <Card>
                    <For each={builtIn()}>{(agent) => <AgentRow agent={agent} busy={busy()} />}</For>
                  </Card>
                </div>
              </Show>
            </Show>
          </Show>
        </Show>
      </PanelBody>
    </PanelScroll>
  )
}

function AgentRow(props: { agent: Agent; onDelete?: () => void; busy: boolean }) {
  const language = useLanguage()
  const label = () => props.agent.native && props.agent.name in LABELS ? language.t(LABELS[props.agent.name as keyof typeof LABELS]) : props.agent.name
  const modeLabel = () =>
    props.agent.mode === "subagent" ? language.t("settings.specialistsOwned.modeSubagent") : props.agent.mode === "all" ? language.t("settings.specialistsOwned.modeBoth") : language.t("settings.specialistsOwned.modePrimary")
  return (
    <Row>
      <Avatar monogram={label().slice(0, 1)} tint={props.agent.color ?? undefined} />
      <div class="min-w-0 flex-1">
        <div class="flex items-center gap-2">
          <span class="text-14-medium text-text-strong truncate">{label()}</span>
          <Chip>{modeLabel()}</Chip>
        </div>
        <Show when={props.agent.description}>
          <p class="text-12-regular text-text-weak truncate mt-0.5">{props.agent.description}</p>
        </Show>
      </div>
      <Show when={props.onDelete}>
        <IconButton icon="trash" variant="ghost" disabled={props.busy} aria-label={language.t("settings.specialistsOwned.delete")} onClick={props.onDelete} />
      </Show>
    </Row>
  )
}

function CreateForm(props: {
  busy: boolean
  onCancel: () => void
  onCreate: (name: string, description: string, prompt: string, mode: Mode) => void
}) {
  const language = useLanguage()
  const [name, setName] = createSignal("")
  const [description, setDescription] = createSignal("")
  const [prompt, setPrompt] = createSignal("")
  const [mode, setMode] = createSignal<Mode>("subagent")
  const valid = () => /^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$/.test(name().trim()) && description().trim().length > 0
  return (
    <div class="flex flex-col gap-4">
      <SectionLabel label={language.t("settings.specialistsOwned.create")} />
      <div class="flex flex-col gap-4 p-5 border border-border-weak-base rounded-[4px] bg-surface-base/40">
        <FormField
          label={language.t("settings.specialistsOwned.name")}
          value={name()}
          onInput={setName}
          placeholder={language.t("settings.specialistsOwned.nameHint")}
        />
        <FormField
          label={language.t("settings.specialistsOwned.descriptionLabel")}
          value={description()}
          onInput={setDescription}
          placeholder={language.t("settings.specialistsOwned.when")}
        />
        <label class="flex flex-col gap-1.5">
          <span class="text-12-medium text-text-strong">{language.t("settings.specialistsOwned.mode")}</span>
          <select
            value={mode()}
            class="h-9 px-3 rounded-xs border border-border-weak-base bg-surface-base text-13-regular text-text-strong outline-none focus:border-border-strong-base"
            onInput={(e) => setMode(e.currentTarget.value as Mode)}
          >
            <option value="subagent">{language.t("settings.specialistsOwned.subagentOption")}</option>
            <option value="primary">{language.t("settings.specialistsOwned.primaryOption")}</option>
            <option value="all">{language.t("settings.specialistsOwned.both")}</option>
          </select>
        </label>
        <FormField
          label={language.t("settings.specialistsOwned.system")}
          value={prompt()}
          onInput={setPrompt}
          multiline
          placeholder={language.t("settings.specialistsOwned.instructions")}
        />
        <div class="flex items-center gap-2">
          <FormButton
            label={props.busy ? language.t("settings.specialistsOwned.creating") : language.t("settings.specialistsOwned.createButton")}
            disabled={props.busy || !valid()}
            onClick={() => props.onCreate(name().trim(), description().trim(), prompt(), mode())}
          />
          <FormButton label={language.t("settings.specialistsOwned.cancel")} variant="ghost" onClick={props.onCancel} disabled={props.busy} />
        </div>
      </div>
    </div>
  )
}

function byName(a: Agent, b: Agent) {
  return a.name.localeCompare(b.name)
}
function message(err: unknown) {
  return err instanceof Error ? err.message : String(err)
}
