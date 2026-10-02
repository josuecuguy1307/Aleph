import { For, Show, createMemo, createSignal, type JSX } from "solid-js"
import { Icon } from "@synsci/ui/icon"
import { Select } from "@synsci/ui/select"
import { Switch } from "@synsci/ui/switch"
import { useLanguage } from "@/context/language"
import { useGlobalSync } from "@/context/global-sync"
import { useModels, type ModelKey } from "@/context/models"
import { displayProviderForModel, modelSummary } from "@/context/model-catalog"
import { CodexConnection } from "./CodexConnection"
import { ProviderKeys } from "./ProviderKeys"
import { modelGroup, modelGroupLabel, modelGroupRank } from "../model-groups"

type Option = {
  key: ModelKey
  label: string
  latest: boolean
  provider: string
  group: ReturnType<typeof modelGroup>
  pinned: boolean
  reasoning: boolean
  context: number
  value: string
}

type Scope = "all" | "reasoning" | "latest" | "long"



export default function Models() {
  const language = useLanguage()
const scopes = (): Array<{ id: Scope; label: string }> => [
  { id: "all", label: language.t("settings.modelsOwned.all") },
  { id: "reasoning", label: language.t("settings.modelsOwned.reasoning") },
  { id: "latest", label: language.t("settings.modelsOwned.latest") },
  { id: "long", label: language.t("settings.modelsOwned.long") },
]
  const sync = useGlobalSync()
  const models = useModels()
  const [query, setQuery] = createSignal("")
  const [scope, setScope] = createSignal<Scope>("all")
  const [error, setError] = createSignal<string>()

  const options = createMemo<Option[]>(() => {
    models.pinned.list()
    return models
      .list()
      .map((item) => {
        const key = { providerID: item.provider.id, modelID: item.id }
        const pinned = models.pinned.has(key)
        return {
          group: modelGroup(item, pinned),
          key,
          label: item.name,
          latest: item.latest,
          pinned,
          reasoning: item.capabilities.reasoning,
          context: item.limit.context,
          provider: displayProviderForModel(item.provider, item.id).name,
          value: `${item.provider.id}/${item.id}`,
        }
      })
      .sort((a, b) => a.label.localeCompare(b.label))
  })
  const filtered = createMemo(() => {
    const terms = query().trim().toLowerCase().split(/\s+/).filter(Boolean)
    return options().filter((model) => {
      if (scope() === "reasoning" && !model.reasoning) return false
      if (scope() === "latest" && !model.latest) return false
      if (scope() === "long" && model.context < 500_000) return false

      const label = modelGroupLabel(model.group).toLowerCase()
      const haystack = `${model.label} ${model.provider} ${model.value} ${label}`.toLowerCase()
      return terms.every((term) => {
        if (term === "is:reasoning") return model.reasoning
        if (term === "is:latest") return model.latest
        if (term === "is:long") return model.context >= 500_000
        if (term.startsWith("provider:")) return `${model.provider} ${label}`.toLowerCase().includes(term.slice(9))
        return haystack.includes(term)
      })
    })
  })
  const primary = () => options().find((model) => model.value === sync.data.config.model)
  const background = () => options().find((model) => model.value === sync.data.config.small_model)
  const groups = createMemo(() => {
    const map = new Map<ReturnType<typeof modelGroup>, Option[]>()
    for (const model of filtered()) map.set(model.group, [...(map.get(model.group) ?? []), model])
    return [...map.entries()]
      .map(([id, items]) => ({ id, label: modelGroupLabel(id), models: items }))
      .sort((a, b) => modelGroupRank(a.id) - modelGroupRank(b.id) || a.label.localeCompare(b.label))
  })
  const [notice, setNotice] = createSignal<{ key: "initial" | "limit" | "pinned" | "unpinned"; name?: string }>({ key: "initial" })

  const togglePin = (model: Option) => {
    const result = models.pinned.toggle(model.key)
    if (result.limited) {
      setNotice({ key: "limit" })
      return
    }
    if (result.pinned) models.setVisibility(model.key, true)
    setNotice({ key: result.pinned ? "pinned" : "unpinned", name: model.label })
  }

  return (
    <div class="flex h-full flex-col overflow-y-auto no-scrollbar">
      <div class="settings-page-header">
        <div class="settings-page-header__inner">
          <h2 class="text-16-medium text-text-strong">{language.t("settings.models.title")}</h2>
          <p class="text-13-regular text-text-weak">
            {language.t("settings.modelsOwned.description")}
          </p>
        </div>
      </div>

      <div class="settings-page-body">
        <Show when={error()}>
          <div
            class="rounded-[4px] px-3 py-2 text-12-regular"
            style={{
              color: "var(--color-error)",
              border: "1px solid var(--color-error-muted)",
            }}
          >
            {error()}
          </div>
        </Show>
        {/* [Aleph · 2026-08-11] EXTIRPADA la sección «Managed inference» ENTERA, con su
            componente `<ManagedInference />`: ofrecía comprar créditos de inferencia del
            proveedor del stack y llevaba, por botón, a su web de planes y billetera.
            En Aleph el cerebro lo pone LA CASA —el compositor dice «Cerebro de Aleph»—, así
            que esto no era una función del workspace sino una vía de pago hacia afuera.
            Sin el componente la sección quedaba como un título sin contenido, de ahí que se
            vaya completa y no sólo su cuerpo.
            El código y su análisis viven en ~/Desktop/CIENCIA-PAGOS-EXTIRPADO/. */}

        <section class="flex flex-col gap-3" aria-labelledby="model-access">
          <div class="flex flex-col gap-0.5">
            <h3 id="model-access" class="text-13-medium text-text-weak">
              ChatGPT / Codex
            </h3>
            <p class="text-12-regular text-text-weak">
              {language.t("settings.modelsOwned.connect")}
            </p>
          </div>
          <CodexConnection onError={setError} />
        </section>

        <section class="flex flex-col gap-3" aria-labelledby="provider-keys">
          <div class="flex flex-col gap-0.5">
            <h3 id="provider-keys" class="text-13-medium text-text-weak">
              {language.t("settings.modelsOwned.keys")}
            </h3>
            <p class="text-12-regular text-text-weak">
              {language.t("settings.modelsOwned.keysHelp")}
            </p>
          </div>
          <ProviderKeys onError={setError} />
        </section>

        <section class="flex flex-col gap-3" aria-labelledby="model-defaults">
          <div class="flex flex-col gap-0.5">
            <h3 id="model-defaults" class="text-13-medium text-text-weak">
              {language.t("settings.modelsOwned.defaults")}
            </h3>
            <p class="text-12-regular text-text-weak">
              {language.t("settings.modelsOwned.effort")}
            </p>
          </div>
          <div class="overflow-hidden rounded-[4px] border border-border-weak-base bg-surface-base/40">
            <Row title={language.t("settings.modelsOwned.research")} detail={language.t("settings.modelsOwned.researchHelp")}>
              <Select
                options={options()}
                current={primary()}
                value={(option) => option.value}
                label={(option) => option.label}
                onSelect={(option) => option && void sync.updateConfig({ model: option.value })}
                variant="secondary"
                size="small"
                triggerVariant="settings"
                placeholder={language.t("settings.modelsOwned.auto")}
              />
            </Row>
            <Row title={language.t("settings.modelsOwned.background")} detail={language.t("settings.modelsOwned.backgroundHelp")}>
              <Select
                options={options()}
                current={background()}
                value={(option) => option.value}
                label={(option) => option.label}
                onSelect={(option) => option && void sync.updateConfig({ small_model: option.value })}
                variant="secondary"
                size="small"
                triggerVariant="settings"
                placeholder={language.t("settings.modelsOwned.auto")}
              />
            </Row>
          </div>
        </section>

        <section class="flex flex-col gap-3" aria-labelledby="model-visibility">
          <div class="flex flex-col gap-0.5">
            <h3 id="model-visibility" class="text-13-medium text-text-weak">
              {language.t("settings.modelsOwned.composer")}
            </h3>
            <p class="text-12-regular text-text-weak">
              {language.t("settings.modelsOwned.composerHelp")}
            </p>
          </div>
          <div class="flex items-center justify-between gap-3">
            <p class="text-11-regular text-text-weak" aria-live="polite">
              {language.t(`settings.modelsOwned.${notice().key}`, { name: notice().name ?? "" })}
            </p>
            <span class="shrink-0 rounded-full border border-border-weak-base px-2 py-0.5 text-11-medium text-text-weak">
              {language.t("settings.modelsOwned.pinCount", { count: models.pinned.list().length })}
            </span>
          </div>
          <div class="flex flex-col gap-2">
            <label class="flex h-9 items-center gap-2 rounded-[7px] border border-border-weak-base bg-surface-base px-3 text-text-weak focus-within:border-border-strong-base">
              <Icon name="magnifying-glass" size="small" />
              <input
                type="search"
                aria-label={language.t("settings.modelsOwned.filter")}
                value={query()}
                onInput={(event) => setQuery(event.currentTarget.value)}
                placeholder={language.t("settings.modelsOwned.search")}
                class="min-w-0 flex-1 bg-transparent text-13-regular text-text-strong outline-none placeholder:text-text-weaker"
              />
            </label>
            <div class="flex flex-wrap items-center gap-1.5" aria-label={language.t("settings.modelsOwned.filters")}>
              <For each={scopes()}>
                {(item) => (
                  <button
                    type="button"
                    aria-pressed={scope() === item.id}
                    onClick={() => setScope(item.id)}
                    class="min-h-7 rounded-[6px] border px-2.5 text-11-medium transition-colors hover:text-text-strong focus-visible:outline focus-visible:outline-1 focus-visible:outline-border-strong"
                    classList={{
                      "border-border-strong-base bg-surface-raised-base text-text-strong": scope() === item.id,
                      "border-border-weak-base bg-transparent text-text-weak": scope() !== item.id,
                    }}
                  >
                    {item.label}
                  </button>
                )}
              </For>
            </div>
          </div>
          <div class="overflow-hidden rounded-[6px] border border-border-weak-base bg-surface-base/40">
            <For each={groups()}>
              {(group) => (
                <section aria-labelledby={`composer-models-${group.id.replace(/[^a-z0-9-]/gi, "-")}`}>
                  <div class="flex min-h-8 items-center border-b border-border-weak-base bg-surface-raised-base/70 px-4">
                    <h4
                      id={`composer-models-${group.id.replace(/[^a-z0-9-]/gi, "-")}`}
                      class="text-11-medium tracking-[0.01em] text-text-weak"
                    >
                      {group.label}
                    </h4>
                  </div>
                  <For each={group.models}>
                    {(model) => (
                      <div class="flex min-h-[52px] items-center justify-between gap-3 border-b border-border-weak-base px-4 py-2.5 last:border-none">
                        <div class="flex min-w-0 flex-1 flex-col gap-0.5">
                          <span class="flex min-w-0 items-center gap-2">
                            <strong class="truncate text-13-medium text-text-strong">{model.label}</strong>
                            <Show when={model.latest}>
                              <span class="shrink-0 text-10-medium text-text-weaker">{language.t("settings.modelsOwned.latest")}</span>
                            </Show>
                          </span>
                          <span class="truncate text-11-regular text-text-weak">
                            {modelSummary({
                              reasoning: model.reasoning,
                              context: model.context,
                              provider: model.provider,
                            })}
                          </span>
                        </div>
                        <div class="flex shrink-0 items-center gap-2">
                          <button
                            type="button"
                            class="flex size-7 items-center justify-center rounded-[5px] text-text-weak hover:bg-surface-raised-base hover:text-text-strong focus-visible:outline focus-visible:outline-1 focus-visible:outline-border-strong"
                            data-pinned={model.pinned ? "true" : undefined}
                            aria-pressed={model.pinned}
                            aria-label={`${model.pinned ? language.t("settings.modelsOwned.unpin") : language.t("settings.modelsOwned.pin")} ${model.label}`}
                            title={model.pinned ? language.t("settings.modelsOwned.removeQuick") : language.t("settings.modelsOwned.pinQuick")}
                            onClick={() => togglePin(model)}
                          >
                            <Icon name={model.pinned ? "pin-filled" : "pin"} size="small" />
                          </button>
                          <Switch
                            hideLabel
                            checked={models.visible(model.key)}
                            onChange={(checked) => models.setVisibility(model.key, checked)}
                          >
                            {`${models.visible(model.key) ? language.t("settings.modelsOwned.hide") : language.t("settings.modelsOwned.show")} ${model.label}`}
                          </Switch>
                        </div>
                      </div>
                    )}
                  </For>
                </section>
              )}
            </For>
            <Show when={filtered().length === 0}>
              <p class="px-4 py-6 text-center text-12-regular text-text-weak">{language.t("settings.modelsOwned.empty")}</p>
            </Show>
          </div>
        </section>
      </div>
    </div>
  )
}

function Row(props: { title: string; detail: string; children: JSX.Element }) {
  return (
    <div class="flex flex-wrap items-center justify-between gap-4 border-b border-border-weak-base px-4 py-3 last:border-none">
      <div class="flex min-w-0 flex-col gap-0.5">
        <span class="text-13-medium text-text-strong">{props.title}</span>
        <span class="text-12-regular text-text-weak">{props.detail}</span>
      </div>
      <div class="flex-shrink-0">{props.children}</div>
    </div>
  )
}
