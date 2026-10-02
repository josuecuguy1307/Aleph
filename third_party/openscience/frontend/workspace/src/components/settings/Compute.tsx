import { For, Show, createEffect, createResource, type Component, type JSX, type Setter } from "solid-js"
import { createStore } from "solid-js/store"
import { Button } from "@synsci/ui/button"
import { Select } from "@synsci/ui/select"
import { Switch } from "@synsci/ui/switch"
import { showToast } from "@synsci/ui/toast"
import { useDialog } from "@synsci/ui/context/dialog"
import { useLanguage } from "@/context/language"
import { useGlobalSDK } from "@/context/global-sdk"
import { usePlatform } from "@/context/platform"
import { confirmDialog } from "@/atlas/dialogs"
import { settingsApi } from "./api"
import { CredentialServices } from "./CredentialServices"
import { ProviderLogo } from "./ProviderLogo"

type Scheduler = "none" | "slurm" | "pbs"
type Host = {
  id: string
  label: string
  host: string
  user?: string
  port?: number
  scheduler: Scheduler
  workdir?: string
}
type Provider = {
  id: string
  connected: boolean
  enabled: boolean
  source: "stored" | "modal_toml" | null
}
type Modal = {
  app: string
  image: string
  network: "unrestricted" | "none"
  timeout_minutes: number
  concurrency: number
}
type Info = {
  providers: Provider[]
  ssh_hosts: Host[]
  modal: Modal
  modal_file: { found: boolean; ready: boolean }
}
type Probe = {
  ok: boolean
  host: string
  latency_ms: number
  hostname?: string
  python: boolean
  gpu: boolean
  slurm: boolean
  pbs: boolean
  error?: string
}
type Notice = {
  tone: "neutral" | "success" | "error"
  title: string
  detail?: string
}

const schedulers = [
  { value: "none" as const, label: "SSH" },
  { value: "slurm" as const, label: "Slurm" },
  { value: "pbs" as const, label: "PBS" },
]

const Compute: Component = () => {
  const language = useLanguage()
  const sdk = useGlobalSDK()
  const platform = usePlatform()
  const dialog = useDialog()
  const fetchFn = platform.fetch ?? fetch
  const call = <T,>(path = "", init?: RequestInit) => settingsApi<T>(sdk.url, fetchFn, `/settings/compute${path}`, init)
  const [data, control] = createResource(() => call<Info>())
  const [state, setState] = createStore({
    adding: false,
    busy: undefined as string | undefined,
    probes: {} as Record<string, Probe>,
    label: "",
    host: "",
    user: "",
    port: "",
    scheduler: "none" as Scheduler,
    workdir: "",
    token: "",
    secret: "",
    app: "",
    image: "",
    network: "none" as Modal["network"],
    timeout: "60",
    concurrency: "10",
    connection: undefined as Notice | undefined,
    defaults: undefined as Notice | undefined,
  })
  const adding = () => state.adding
  const setAdding: Setter<boolean> = (value) => setState("adding", value)
  const busy = () => state.busy
  const setBusy = (value: string | undefined) => {
    setState("busy", value)
    return value
  }
  const probes = () => state.probes
  const setProbes: Setter<Record<string, Probe>> = (value) => setState("probes", value)
  const label = () => state.label
  const setLabel: Setter<string> = (value) => setState("label", value)
  const host = () => state.host
  const setHost: Setter<string> = (value) => setState("host", value)
  const user = () => state.user
  const setUser: Setter<string> = (value) => setState("user", value)
  const port = () => state.port
  const setPort: Setter<string> = (value) => setState("port", value)
  const scheduler = () => state.scheduler
  const setScheduler: Setter<Scheduler> = (value) => setState("scheduler", value)
  const workdir = () => state.workdir
  const setWorkdir: Setter<string> = (value) => setState("workdir", value)
  const token = () => state.token
  const setToken: Setter<string> = (value) => setState("token", value)
  const secret = () => state.secret
  const setSecret: Setter<string> = (value) => setState("secret", value)
  const app = () => state.app
  const setApp: Setter<string> = (value) => setState("app", value)
  const image = () => state.image
  const setImage: Setter<string> = (value) => setState("image", value)
  const network = () => state.network
  const setNetwork: Setter<Modal["network"]> = (value) => setState("network", value)
  const timeout = () => state.timeout
  const setTimeout: Setter<string> = (value) => setState("timeout", value)
  const concurrency = () => state.concurrency
  const setConcurrency: Setter<string> = (value) => setState("concurrency", value)
  const connection = () => state.connection
  const setConnection = (value: Notice | undefined) => {
    setState("connection", value)
    return value
  }
  const defaults = () => state.defaults
  const setDefaults = (value: Notice | undefined) => {
    setState("defaults", value)
    return value
  }
  const modal = () => data()?.providers.find((item) => item.id === "modal")
  const dirty = () => {
    const value = data()?.modal
    if (!value) return false
    return (
      app().trim() !== value.app ||
      image().trim() !== value.image ||
      network() !== value.network ||
      timeout().trim() !== String(value.timeout_minutes) ||
      concurrency().trim() !== String(value.concurrency)
    )
  }
  const connectionNotice = (): Notice | undefined => {
    const current = connection()
    if (current) return current
    if (!modal()?.connected) return undefined
    if (!modal()?.enabled) {
      return { tone: "neutral", title: language.t("settings.computeOwned.text1"), detail: language.t("settings.computeOwned.text2") }
    }
    return {
      tone: "neutral",
      title: language.t("settings.computeOwned.text3"),
      detail: language.t("settings.computeOwned.text4"),
    }
  }
  const defaultsNotice = (): Notice | undefined => {
    if (!modal()?.connected) return undefined
    const current = defaults()
    if (current?.tone === "error" || busy() === "modal:save") return current
    if (dirty()) {
      return {
        tone: "neutral",
        title: language.t("settings.computeOwned.text5"),
        detail: language.t("settings.computeOwned.text6"),
      }
    }
    return (
      current ?? {
        tone: "neutral",
        title: language.t("settings.computeOwned.text7"),
        detail: language.t("settings.computeOwned.text8"),
      }
    )
  }

  createEffect(() => {
    const value = data()?.modal
    if (!value) return
    setApp(value.app)
    setImage(value.image)
    setNetwork(value.network)
    setTimeout(String(value.timeout_minutes))
    setConcurrency(String(value.concurrency))
  })

  const connect = async () => {
    setBusy("modal:connect")
    setConnection({ tone: "neutral", title: language.t("settings.computeOwned.text9") })
    const next = await call<Info>("/provider/modal", {
      method: "POST",
      body: JSON.stringify({ key: `${token().trim()} : ${secret().trim()}` }),
    }).catch((error) => {
      const detail = message(error)
      setConnection({ tone: "error", title: language.t("settings.computeOwned.text10"), detail })
      showToast({ title: language.t("settings.computeOwned.text10"), description: detail })
      return undefined
    })
    setBusy(undefined)
    if (!next) return
    control.mutate(next)
    setToken("")
    setSecret("")
    setConnection({
      tone: "success",
      title: language.t("settings.computeOwned.text11"),
      detail: language.t("settings.computeOwned.text12"),
    })
    showToast({
      variant: "success",
      title: language.t("settings.computeOwned.text11"),
      description: language.t("settings.computeOwned.text13"),
    })
  }

  const configure = async () => {
    setBusy("modal:configure")
    setConnection({ tone: "neutral", title: language.t("settings.computeOwned.text14"), detail: language.t("settings.computeOwned.text15") })
    const next = await call<Info>("/modal/configure", { method: "POST" }).catch((error) => {
      const detail = message(error)
      setConnection({ tone: "error", title: language.t("settings.computeOwned.text16"), detail })
      showToast({ title: language.t("settings.computeOwned.text16"), description: detail })
      return undefined
    })
    setBusy(undefined)
    if (!next) return
    control.mutate(next)
    setConnection({
      tone: "success",
      title: language.t("settings.computeOwned.text17"),
      detail: language.t("settings.computeOwned.text18"),
    })
    showToast({
      variant: "success",
      title: language.t("settings.computeOwned.text17"),
      description: language.t("settings.computeOwned.text19"),
    })
  }

  const toggle = async (enabled: boolean) => {
    setBusy("modal:toggle")
    setConnection({ tone: "neutral", title: enabled ? language.t("settings.computeOwned.text20") : language.t("settings.computeOwned.text21") })
    const next = await call<Info>("/provider/modal/enabled", {
      method: "POST",
      body: JSON.stringify({ enabled }),
    }).catch((error) => {
      const detail = message(error)
      setConnection({ tone: "error", title: language.t("settings.computeOwned.text22"), detail })
      showToast({ title: language.t("settings.computeOwned.text22"), description: detail })
      return undefined
    })
    setBusy(undefined)
    if (!next) return
    control.mutate(next)
    setConnection({
      tone: "success",
      title: enabled ? language.t("settings.computeOwned.text23") : language.t("settings.computeOwned.text24"),
      detail: enabled
        ? language.t("settings.computeOwned.text25")
        : language.t("settings.computeOwned.text26"),
    })
  }

  const check = async () => {
    setBusy("modal:check")
    setConnection({ tone: "neutral", title: language.t("settings.computeOwned.text27"), detail: language.t("settings.computeOwned.text28") })
    const result = await call<{ ok: true; sdk: string }>("/modal/check", { method: "POST" }).catch((error) => {
      const detail = message(error)
      setConnection({ tone: "error", title: language.t("settings.computeOwned.text29"), detail })
      showToast({ title: language.t("settings.computeOwned.text30"), description: detail })
      return undefined
    })
    setBusy(undefined)
    if (!result) return
    setConnection({
      tone: "success",
      title: language.t("settings.computeOwned.text31"),
      detail: language.t("settings.computeOwned.accepted", { sdk: result.sdk }),
    })
    showToast({ variant: "success", title: language.t("settings.computeOwned.text32"), description: language.t("settings.computeOwned.connected", { sdk: result.sdk }) })
  }

  const saveModal = async () => {
    const minutes = Number(timeout())
    if (!Number.isInteger(minutes) || minutes < 1 || minutes > 1_440) {
      setDefaults({
        tone: "error",
        title: language.t("settings.computeOwned.text33"),
        detail: language.t("settings.computeOwned.text34"),
      })
      showToast({ title: language.t("settings.computeOwned.text35"), description: language.t("settings.computeOwned.text36") })
      return
    }
    const limit = Number(concurrency())
    if (!Number.isInteger(limit) || limit < 1 || limit > 100) {
      setDefaults({
        tone: "error",
        title: language.t("settings.computeOwned.text33"),
        detail: language.t("settings.computeOwned.text37"),
      })
      showToast({ title: language.t("settings.computeOwned.text38"), description: language.t("settings.computeOwned.text39") })
      return
    }
    setBusy("modal:save")
    setDefaults({ tone: "neutral", title: language.t("settings.computeOwned.text40") })
    const next = await call<Info>("/modal", {
      method: "PATCH",
      body: JSON.stringify({
        app: app().trim(),
        image: image().trim(),
        network: network(),
        timeout_minutes: minutes,
        concurrency: limit,
      }),
    }).catch((error) => {
      const detail = message(error)
      setDefaults({ tone: "error", title: language.t("settings.computeOwned.text33"), detail })
      showToast({ title: language.t("settings.computeOwned.text41"), description: detail })
      return undefined
    })
    setBusy(undefined)
    if (!next) return
    control.mutate(next)
    setDefaults({
      tone: "success",
      title: language.t("settings.computeOwned.text42"),
      detail: language.t("settings.computeOwned.text43"),
    })
    showToast({ variant: "success", title: language.t("settings.computeOwned.text44") })
  }

  const reset = () => {
    setLabel("")
    setHost("")
    setUser("")
    setPort("")
    setScheduler("none")
    setWorkdir("")
    setAdding(false)
  }

  const add = async () => {
    const parsedPort = port().trim() ? Number(port()) : undefined
    if (parsedPort !== undefined && (!Number.isInteger(parsedPort) || parsedPort < 1 || parsedPort > 65_535)) {
      showToast({ title: language.t("settings.computeOwned.text45"), description: language.t("settings.computeOwned.text46") })
      return
    }
    setBusy("add")
    const next = await call<Info>("/ssh", {
      method: "POST",
      body: JSON.stringify({
        label: label().trim(),
        host: host().trim(),
        user: user().trim() || undefined,
        port: parsedPort,
        scheduler: scheduler(),
        workdir: workdir().trim() || undefined,
      }),
    }).catch((error) => {
      showToast({ title: language.t("settings.computeOwned.text47"), description: message(error) })
      return undefined
    })
    setBusy(undefined)
    if (!next) return
    control.mutate(next)
    reset()
    showToast({ variant: "success", title: language.t("settings.computeOwned.text48"), description: language.t("settings.computeOwned.text49") })
  }

  const test = async (item: Host) => {
    setBusy(`test:${item.id}`)
    const result = await call<Probe>(`/ssh/${item.id}/test`, { method: "POST" }).catch((error) => ({
      ok: false,
      host: item.label,
      latency_ms: 0,
      python: false,
      gpu: false,
      slurm: false,
      pbs: false,
      error: message(error),
    }))
    setProbes((current) => ({ ...current, [item.id]: result }))
    setBusy(undefined)
    showToast({
      variant: result.ok ? "success" : "error",
      title: result.ok ? language.t("settings.computeOwned.reachable", { name: item.label }) : language.t("settings.computeOwned.unreachable", { name: item.label }),
      description: result.ok ? `${result.latency_ms} ms · ${capabilities(result)}` : result.error,
    })
  }

  const remove = async (item: Host) => {
    const confirmed = await confirmDialog(dialog, {
      title: language.t("settings.computeOwned.removeConfirm", { name: item.label }),
      message: language.t("settings.computeOwned.text50"),
      confirmLabel: language.t("settings.computeOwned.text51"),
      danger: true,
    })
    if (!confirmed) return
    setBusy(`remove:${item.id}`)
    const next = await call<Info>(`/ssh/${item.id}`, { method: "DELETE" }).catch((error) => {
      showToast({ title: language.t("settings.computeOwned.text52"), description: message(error) })
      return undefined
    })
    setBusy(undefined)
    if (!next) return
    control.mutate(next)
    setProbes((current) => Object.fromEntries(Object.entries(current).filter(([id]) => id !== item.id)))
  }

  return (
    <div class="flex flex-col h-full overflow-y-auto no-scrollbar">
      <div class="settings-page-header">
        <div class="settings-page-header__inner">
          <h2 class="text-16-medium text-text-strong">Compute</h2>
          <p class="text-13-regular text-text-weak">
            {language.t("settings.computeOwned.text53")}
          </p>
        </div>
      </div>

      <div class="settings-page-body">
        <Section title={language.t("settings.computeOwned.text54")} subtitle={language.t("settings.computeOwned.text55")}>
          <Panel>
            <Row title={language.t("settings.computeOwned.text56")} subtitle={language.t("settings.computeOwned.text57")}>
              <Badge tone="ready">{language.t("settings.computeOwned.text58")}</Badge>
            </Row>
          </Panel>
        </Section>

        <CredentialServices
          category="compute"
          title={language.t("settings.computeOwned.text59")}
          description={language.t("settings.computeOwned.text60")}
        />

        <Section title="Modal" subtitle={language.t("settings.computeOwned.text61")}>
          <Panel>
            <div class="flex flex-col gap-4 px-4 py-4">
              <div class="flex flex-wrap items-center justify-between gap-4">
                <div class="flex min-w-0 items-center gap-2.5">
                  <ProviderLogo id="modal" label="Modal" connected={modal()?.connected} />
                  <div class="flex min-w-0 flex-col gap-0.5">
                    <span class="text-14-medium text-text-strong">{language.t("settings.computeOwned.text62")}</span>
                    <span class="text-12-regular text-text-weak">
                      {modal()?.connected
                        ? modal()?.source === "modal_toml"
                          ? language.t("settings.computeOwned.text63")
                          : language.t("settings.computeOwned.text64")
                        : data()?.modal_file.ready
                          ? language.t("settings.computeOwned.text65")
                          : data()?.modal_file.found
                            ? language.t("settings.computeOwned.text66")
                            : language.t("settings.computeOwned.text67")}
                    </span>
                  </div>
                </div>
                <Show when={modal()?.connected}>
                  <Switch
                    hideLabel
                    checked={modal()?.enabled ?? false}
                    disabled={Boolean(busy())}
                    onChange={(value) => void toggle(value)}
                  >
                    {language.t("settings.computeOwned.text68")}
                  </Switch>
                </Show>
              </div>
              <Show when={connectionNotice()}>{(notice) => <NoticeBox notice={notice()} />}</Show>
              <Show when={!data.loading && !modal()?.connected && data()?.modal_file.ready}>
                <div class="flex flex-wrap items-center justify-between gap-3 rounded-[6px] border border-border-weak-base bg-surface-base px-3 py-3">
                  <p class="text-12-regular text-text-weak">
                    {language.t("settings.computeOwned.text69")}
                  </p>
                  <Button size="small" variant="primary" disabled={Boolean(busy())} onClick={() => void configure()}>
                    {busy() === "modal:configure" ? language.t("settings.computeOwned.text70") : language.t("settings.computeOwned.text71")}
                  </Button>
                </div>
              </Show>
              <Show when={!data.loading && !modal()?.connected && !data()?.modal_file.ready}>
                <div class="flex flex-col gap-2">
                  <div class="grid gap-3 sm:grid-cols-2">
                    <Field label={language.t("settings.computeOwned.text72")} value={token()} placeholder="ak-…" onInput={setToken} />
                    <Field
                      label={language.t("settings.computeOwned.text73")}
                      value={secret()}
                      placeholder="as-…"
                      type="password"
                      onInput={setSecret}
                    />
                  </div>
                  <div class="flex justify-end">
                    <Button
                      size="small"
                      variant="primary"
                      disabled={!token().trim() || !secret().trim() || Boolean(busy())}
                      onClick={() => void connect()}
                    >
                      {busy() === "modal:connect" ? language.t("settings.computeOwned.text74") : language.t("settings.computeOwned.text75")}
                    </Button>
                  </div>
                </div>
              </Show>
              <Show when={modal()?.connected}>
                <div class="grid gap-3 sm:grid-cols-2">
                  <Field label={language.t("settings.computeOwned.text76")} value={app()} placeholder="openscience" onInput={setApp} />
                  <Field label={language.t("settings.computeOwned.text77")} value={image()} placeholder="python:3.12-slim" onInput={setImage} />
                  <label class="flex flex-col gap-1.5">
                    <span class="text-12-medium text-text-strong">{language.t("settings.computeOwned.text78")}</span>
                    <select
                      aria-label={language.t("settings.computeOwned.text79")}
                      class="h-9 px-3 rounded-xs border border-border-weak-base bg-surface-base text-13-regular text-text-strong"
                      value={network()}
                      onChange={(event) => setNetwork(event.currentTarget.value as Modal["network"])}
                    >
                      <option value="none">{language.t("settings.computeOwned.text80")}</option>
                      <option value="unrestricted">{language.t("settings.computeOwned.text81")}</option>
                    </select>
                  </label>
                  <Field
                    label={language.t("settings.computeOwned.text82")}
                    value={timeout()}
                    placeholder="60"
                    inputMode="numeric"
                    onInput={setTimeout}
                  />
                  <Field
                    label={language.t("settings.computeOwned.text83")}
                    value={concurrency()}
                    placeholder="10"
                    inputMode="numeric"
                    onInput={setConcurrency}
                  />
                </div>
                <p class="text-11-regular text-text-weak">
                  {language.t("settings.computeOwned.text84")}
                </p>
                <Show when={defaultsNotice()}>{(notice) => <NoticeBox notice={notice()} />}</Show>
                <p class="text-11-regular text-text-weak">
                  {language.t("settings.computeOwned.text85")}
                </p>
                <div class="flex justify-end gap-2">
                  <Button
                    size="small"
                    variant="secondary"
                    disabled={!modal()?.enabled || Boolean(busy())}
                    onClick={() => void check()}
                  >
                    {busy() === "modal:check" ? language.t("settings.computeOwned.text86") : language.t("settings.computeOwned.text87")}
                  </Button>
                  <Button
                    size="small"
                    variant="primary"
                    disabled={!app().trim() || !image().trim() || Boolean(busy())}
                    onClick={() => void saveModal()}
                  >
                    {busy() === "modal:save" ? language.t("settings.computeOwned.text74") : language.t("settings.computeOwned.text88")}
                  </Button>
                </div>
              </Show>
            </div>
          </Panel>
        </Section>

        <Section title={language.t("settings.computeOwned.text89")} subtitle={language.t("settings.computeOwned.text90")}>
          <div class="flex flex-col gap-3">
            <Show
              when={!data.loading}
              fallback={
                <Panel>
                  <Row title={language.t("settings.computeOwned.text91")} subtitle={language.t("settings.computeOwned.text92")}>
                    <Badge>{language.t("settings.computeOwned.text93")}</Badge>
                  </Row>
                </Panel>
              }
            >
              <Show
                when={(data()?.ssh_hosts.length ?? 0) > 0}
                fallback={
                  <Panel>
                    <Row
                      title={language.t("settings.computeOwned.text94")}
                      subtitle={language.t("settings.computeOwned.text95")}
                    >
                      <Button size="small" variant="secondary" onClick={() => setAdding(true)}>
                        {language.t("settings.computeOwned.text96")}
                      </Button>
                    </Row>
                  </Panel>
                }
              >
                <Panel>
                  <For each={data()?.ssh_hosts}>
                    {(item) => {
                      const probe = () => probes()[item.id]
                      return (
                        <div class="flex flex-wrap items-center gap-4 px-4 py-3.5 border-b border-border-weak-base last:border-none">
                          <div class="min-w-0 flex-1">
                            <div class="flex items-center gap-2">
                              <span class="text-14-medium text-text-strong truncate">{item.label}</span>
                              <Badge tone={probe()?.ok ? "ready" : undefined}>
                                {probe()?.ok ? language.t("settings.computeOwned.text97") : schedulerLabel(item.scheduler)}
                              </Badge>
                            </div>
                            <p class="text-12-regular text-text-weak mt-0.5 truncate">
                              {destination(item)}
                              {item.workdir ? ` · ${item.workdir}` : ""}
                            </p>
                            <Show when={probe()}>
                              {(result) => (
                                <p
                                  class={
                                    result().ok
                                      ? "text-11-regular text-text-success mt-1"
                                      : "text-11-regular text-text-danger mt-1"
                                  }
                                >
                                  {result().ok
                                    ? `${result().latency_ms} ms · ${capabilities(result())}`
                                    : result().error}
                                </p>
                              )}
                            </Show>
                          </div>
                          <div class="flex items-center gap-2">
                            <Button
                              size="small"
                              variant="secondary"
                              disabled={Boolean(busy())}
                              onClick={() => void test(item)}
                            >
                              {busy() === `test:${item.id}` ? language.t("settings.computeOwned.text86") : language.t("settings.computeOwned.text98")}
                            </Button>
                            <Button
                              size="small"
                              variant="ghost"
                              disabled={Boolean(busy())}
                              onClick={() => void remove(item)}
                            >
                              {language.t("settings.computeOwned.text99")}
                            </Button>
                          </div>
                        </div>
                      )
                    }}
                  </For>
                </Panel>
              </Show>
            </Show>

            <Show when={(data()?.ssh_hosts.length ?? 0) > 0 && !adding()}>
              <Button size="small" variant="secondary" onClick={() => setAdding(true)}>
                {language.t("settings.computeOwned.text100")}
              </Button>
            </Show>

            <Show when={adding()}>
              <form
                class="grid gap-4 border border-border-weak-base rounded-[6px] bg-surface-base/40 p-4"
                onSubmit={(event) => {
                  event.preventDefault()
                  void add()
                }}
              >
                <div>
                  <h4 class="text-14-medium text-text-strong">{language.t("settings.computeOwned.text101")}</h4>
                  <p class="text-12-regular text-text-weak mt-0.5">
                    {language.t("settings.computeOwned.text102")}
                  </p>
                </div>
                <div class="grid gap-3 sm:grid-cols-2">
                  <Field label={language.t("settings.computeOwned.text103")} value={label()} placeholder={language.t("settings.computeOwned.text104")} onInput={setLabel} />
                  <Field label={language.t("settings.computeOwned.text105")} value={host()} placeholder="hpc.example.edu" onInput={setHost} />
                  <Field label={language.t("settings.computeOwned.text106")} value={user()} placeholder={language.t("settings.computeOwned.text107")} onInput={setUser} />
                  <Field label={language.t("settings.computeOwned.text108")} value={port()} placeholder="22" inputMode="numeric" onInput={setPort} />
                  <label class="flex flex-col gap-1.5">
                    <span class="text-12-medium text-text-strong">{language.t("settings.computeOwned.text109")}</span>
                    <Select
                      aria-label={language.t("settings.computeOwned.text109")}
                      options={schedulers}
                      current={schedulers.find((item) => item.value === scheduler())}
                      value={(item) => item.value}
                      label={(item) => item.label}
                      onSelect={(item) => item && setScheduler(item.value)}
                      variant="secondary"
                      size="small"
                      triggerVariant="settings"
                    />
                  </label>
                  <Field
                    label={language.t("settings.computeOwned.text110")}
                    value={workdir()}
                    placeholder="~/research"
                    onInput={setWorkdir}
                  />
                </div>
                <div class="flex items-center justify-end gap-2">
                  <Button size="small" variant="ghost" disabled={busy() === "add"} onClick={reset}>
                    {language.t("settings.computeOwned.text111")}
                  </Button>
                  <Button
                    type="submit"
                    size="small"
                    variant="primary"
                    disabled={!label().trim() || !host().trim() || busy() === "add"}
                  >
                    {busy() === "add" ? language.t("settings.computeOwned.text112") : language.t("settings.computeOwned.text96")}
                  </Button>
                </div>
              </form>
            </Show>
          </div>
        </Section>
      </div>
    </div>
  )
}

export default Compute

const Field: Component<{
  label: string
  value: string
  placeholder: string
  type?: JSX.InputHTMLAttributes<HTMLInputElement>["type"]
  inputMode?: JSX.InputHTMLAttributes<HTMLInputElement>["inputMode"]
  onInput: (value: string) => void
}> = (props) => (
  <label class="flex flex-col gap-1.5">
    <span class="text-12-medium text-text-strong">{props.label}</span>
    <input
      class="h-9 px-3 rounded-xs border border-border-weak-base bg-surface-base text-13-regular text-text-strong outline-none focus:border-border-strong-base"
      value={props.value}
      placeholder={props.placeholder}
      type={props.type}
      inputMode={props.inputMode}
      onInput={(event) => props.onInput(event.currentTarget.value)}
    />
  </label>
)

const Section: Component<{ title: string; subtitle: string; children: JSX.Element }> = (props) => (
  <section class="flex flex-col gap-3">
    <div class="flex flex-col gap-0.5">
      <h3 class="text-13-medium text-text-weak tracking-wide">{props.title}</h3>
      <p class="text-12-regular text-text-weak">{props.subtitle}</p>
    </div>
    {props.children}
  </section>
)

const Panel: Component<{ children: JSX.Element }> = (props) => (
  <div class="border border-border-weak-base rounded-[6px] overflow-hidden bg-surface-base/40">{props.children}</div>
)

const NoticeBox: Component<{ notice: Notice }> = (props) => (
  <div
    role={props.notice.tone === "error" ? "alert" : "status"}
    aria-live="polite"
    class="flex items-start gap-2.5 rounded-[6px] border px-3 py-2.5"
    classList={{
      "border-border-weak-base bg-surface-base/60": props.notice.tone === "neutral",
      "border-text-success/30 bg-text-success/5": props.notice.tone === "success",
      "border-text-danger/30 bg-text-danger/5": props.notice.tone === "error",
    }}
  >
    <span
      class="mt-1 size-1.5 shrink-0 rounded-full"
      classList={{
        "bg-icon-weak-base": props.notice.tone === "neutral",
        "bg-icon-success-base": props.notice.tone === "success",
        "bg-text-danger": props.notice.tone === "error",
      }}
      aria-hidden="true"
    />
    <div class="min-w-0">
      <p
        class="text-12-medium"
        classList={{
          "text-text-strong": props.notice.tone === "neutral",
          "text-text-success": props.notice.tone === "success",
          "text-text-danger": props.notice.tone === "error",
        }}
      >
        {props.notice.title}
      </p>
      <Show when={props.notice.detail}>
        <p class="mt-0.5 text-11-regular text-text-weak">{props.notice.detail}</p>
      </Show>
    </div>
  </div>
)

const Row: Component<{ title: string; subtitle: string; children: JSX.Element }> = (props) => (
  <div class="flex flex-wrap items-center justify-between gap-4 px-4 py-3.5">
    <div class="flex flex-col gap-0.5 min-w-0">
      <span class="text-14-medium text-text-strong">{props.title}</span>
      <span class="text-12-regular text-text-weak">{props.subtitle}</span>
    </div>
    <div class="flex-shrink-0">{props.children}</div>
  </div>
)

const Badge: Component<{ tone?: "ready"; children: JSX.Element }> = (props) => (
  <span
    class={
      props.tone === "ready"
        ? "inline-flex items-center gap-1.5 text-11-medium text-text-success"
        : "inline-flex items-center rounded-[4px] px-2 py-1 text-11-medium text-text-weak bg-surface-base"
    }
  >
    {props.tone === "ready" ? <span class="size-1.5 rounded-full bg-current" aria-hidden="true" /> : undefined}
    {props.children}
  </span>
)

function destination(host: Host) {
  const login = host.user ? `${host.user}@${host.host}` : host.host
  return host.port ? `${login}:${host.port}` : login
}

function schedulerLabel(scheduler: Scheduler) {
  if (scheduler === "slurm") return "Slurm"
  if (scheduler === "pbs") return "PBS"
  return "SSH"
}

function capabilities(probe: Probe) {
  const values = [
    probe.hostname,
    probe.python ? "Python" : undefined,
    probe.gpu ? "GPU" : undefined,
    probe.slurm ? "Slurm" : undefined,
    probe.pbs ? "PBS" : undefined,
  ]
  return values.filter((value): value is string => Boolean(value)).join(" · ") || "SSH"
}

function message(error: unknown) {
  return error instanceof Error ? error.message : String(error)
}
