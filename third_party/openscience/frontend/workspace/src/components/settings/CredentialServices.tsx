import { Button } from "@synsci/ui/button"
import { type Component, type JSX, For, Show, createMemo, createSignal, onMount } from "solid-js"
import { useLanguage } from "@/context/language"
import { useGlobalSDK } from "@/context/global-sdk"
import { usePlatform } from "@/context/platform"
import { settingsApi } from "./api"
import { ProviderLogo } from "./ProviderLogo"

type Field = {
  name: string
  label: string
  type: "password" | "text" | "textarea"
  optional: boolean
  placeholder?: string
}

type Service = {
  id: string
  label: string
  description: string
  category?: "compute" | "integration"
  custom: boolean
  fields: Field[]
  connected: boolean
  set_fields: string[]
  updated_at: string | null
}

export const CredentialServices: Component<{
  category: "compute" | "integration"
  title: string
  description: string
  custom?: boolean
}> = (props) => {
  const language = useLanguage()
  const sdk = useGlobalSDK()
  const platform = usePlatform()
  const [services, setServices] = createSignal<Service[]>([])
  const [error, setError] = createSignal<string>()
  const [editing, setEditing] = createSignal<string>()
  const [values, setValues] = createSignal<Record<string, string>>({})
  const [saving, setSaving] = createSignal(false)
  const [custom, setCustom] = createSignal(false)
  const [name, setName] = createSignal("")
  const [field, setField] = createSignal("api_key")
  const [secret, setSecret] = createSignal("")
  const category = (service: Service) => {
    if (service.category) return service.category
    if (["aws", "gcp", "azure", "nvidia"].includes(service.id)) return "compute"
    if (service.id === "modal") return undefined
    return "integration"
  }
  const items = createMemo(() => services().filter((service) => category(service) === props.category))
  const count = createMemo(() => items().filter((service) => service.connected).length)

  const load = async () => {
    setError(undefined)
    const result = await settingsApi<{ services: Service[] }>(
      sdk.url,
      platform.fetch ?? fetch,
      "/settings/credentials",
    ).catch((cause) => {
      setError(cause instanceof Error ? cause.message : String(cause))
      return undefined
    })
    if (result) setServices(result.services)
  }

  onMount(() => void load())

  const open = (id: string) => {
    setValues({})
    setEditing(editing() === id ? undefined : id)
  }

  const ready = (service: Service) => {
    const required = service.fields.filter((item) => !item.optional)
    if (required.length) {
      return required.every((item) => service.set_fields.includes(item.name) || Boolean(values()[item.name]?.trim()))
    }
    return service.fields.some((item) => service.set_fields.includes(item.name) || Boolean(values()[item.name]?.trim()))
  }

  const save = async (id: string, fields = values(), label?: string) => {
    if (saving()) return false
    setSaving(true)
    setError(undefined)
    const result = await settingsApi<{ services: Service[] }>(
      sdk.url,
      platform.fetch ?? fetch,
      `/settings/credentials/${encodeURIComponent(id)}`,
      {
        method: "PUT",
        body: JSON.stringify({ fields, ...(label ? { label } : {}) }),
      },
    ).catch((cause) => {
      setError(cause instanceof Error ? cause.message : String(cause))
      return undefined
    })
    setSaving(false)
    if (!result) return false
    setServices(result.services)
    setEditing(undefined)
    setValues({})
    return true
  }

  const remove = async (service: Service) => {
    if (!window.confirm(language.t("settings.credentialServices.confirm", { name: service.label }))) return
    setError(undefined)
    const result = await settingsApi<{ services: Service[] }>(
      sdk.url,
      platform.fetch ?? fetch,
      `/settings/credentials/${encodeURIComponent(service.id)}`,
      { method: "DELETE" },
    ).catch((cause) => {
      setError(cause instanceof Error ? cause.message : String(cause))
      return undefined
    })
    if (result) setServices(result.services)
  }

  const add = async () => {
    const label = name().trim()
    const value = secret().trim()
    const key = field().trim() || "api_key"
    if (!label || !value) return
    const slug = label
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
    if (!slug) return
    const saved = await save(`custom:${slug}`, { [key]: value }, label)
    if (!saved) return
    setCustom(false)
    setName("")
    setField("api_key")
    setSecret("")
  }

  return (
    <section class="credential-services">
      <div class="settings-section-heading">
        <div>
          <h3>{props.title}</h3>
          <p>{props.description}</p>
        </div>
        <span>{language.t("settings.credentialServices.count", { count: count() })}</span>
      </div>

      <Show when={error()}>
        <div class="settings-error" role="alert">
          {error()}
        </div>
      </Show>

      <div class="settings-list">
        <For each={items()}>
          {(service) => (
            <div class="settings-list-item">
              <div class="settings-list-row">
                <ProviderLogo id={service.id} label={service.label} connected={service.connected} />
                <div class="settings-list-copy">
                  <strong>{service.label}</strong>
                  <span>{service.connected ? language.t("settings.credentialServices.text1") : service.description}</span>
                </div>
                <div class="settings-list-actions">
                  <Show when={service.connected}>
                    <Button size="small" variant="ghost" onClick={() => void remove(service)}>
                      {language.t("settings.credentialServices.text2")}
                    </Button>
                  </Show>
                  <Button
                    size="small"
                    variant={service.connected ? "secondary" : "primary"}
                    onClick={() => open(service.id)}
                  >
                    {editing() === service.id ? language.t("settings.credentialServices.text3") : service.connected ? language.t("settings.credentialServices.text4") : language.t("settings.credentialServices.text5")}
                  </Button>
                </div>
              </div>

              <Show when={editing() === service.id}>
                <form
                  class="credential-form"
                  onSubmit={(event) => {
                    event.preventDefault()
                    void save(service.id)
                  }}
                >
                  <For each={service.fields}>
                    {(item) => (
                      <label>
                        <span>
                          {item.label}
                          {item.optional ? language.t("settings.credentialServices.text6") : ""}
                          {service.set_fields.includes(item.name) ? language.t("settings.credentialServices.text7") : ""}
                        </span>
                        <Show
                          when={item.type === "textarea"}
                          fallback={
                            <input
                              type={item.type === "password" ? "password" : "text"}
                              autocomplete="off"
                              spellcheck={false}
                              value={values()[item.name] ?? ""}
                              placeholder={
                                item.placeholder ??
                                (service.set_fields.includes(item.name) ? language.t("settings.credentialServices.text8") : "")
                              }
                              onInput={(event) => setValues({ ...values(), [item.name]: event.currentTarget.value })}
                            />
                          }
                        >
                          <textarea
                            autocomplete="off"
                            spellcheck={false}
                            value={values()[item.name] ?? ""}
                            placeholder={
                              item.placeholder ??
                              (service.set_fields.includes(item.name) ? language.t("settings.credentialServices.text8") : "")
                            }
                            onInput={(event) => setValues({ ...values(), [item.name]: event.currentTarget.value })}
                          />
                        </Show>
                      </label>
                    )}
                  </For>
                  <div class="credential-form-actions">
                    <Button type="submit" size="small" variant="primary" disabled={saving() || !ready(service)}>
                      {saving() ? language.t("settings.credentialServices.text9") : language.t("settings.credentialServices.text10")}
                    </Button>
                    <Button type="button" size="small" variant="ghost" onClick={() => setEditing(undefined)}>
                      {language.t("settings.credentialServices.text3")}
                    </Button>
                  </div>
                </form>
              </Show>
            </div>
          )}
        </For>
      </div>

      <Show when={props.custom}>
        <Show
          when={custom()}
          fallback={
            <button class="settings-add-row" type="button" onClick={() => setCustom(true)}>
              {language.t("settings.credentialServices.text11")}
            </button>
          }
        >
          <form
            class="credential-form credential-form--custom"
            onSubmit={(event) => {
              event.preventDefault()
              void add()
            }}
          >
            <div class="credential-form-grid">
              <Field label={language.t("settings.credentialServices.text12")} value={name()} placeholder={language.t("settings.credentialServices.text13")} onInput={setName} />
              <Field label={language.t("settings.credentialServices.text14")} value={field()} placeholder="api_key" onInput={setField} />
            </div>
            <Field
              label={language.t("settings.credentialServices.text15")}
              value={secret()}
              type="password"
              placeholder={language.t("settings.credentialServices.text16")}
              onInput={setSecret}
            />
            <p>{language.t("settings.credentialServices.text17")}</p>
            <div class="credential-form-actions">
              <Button
                type="submit"
                size="small"
                variant="primary"
                disabled={saving() || !name().trim() || !secret().trim()}
              >
                {saving() ? language.t("settings.credentialServices.text9") : language.t("settings.credentialServices.text10")}
              </Button>
              <Button type="button" size="small" variant="ghost" onClick={() => setCustom(false)}>
                {language.t("settings.credentialServices.text3")}
              </Button>
            </div>
          </form>
        </Show>
      </Show>
    </section>
  )
}

const Field: Component<{
  label: string
  value: string
  placeholder: string
  type?: JSX.InputHTMLAttributes<HTMLInputElement>["type"]
  onInput: (value: string) => void
}> = (props) => (
  <label>
    <span>{props.label}</span>
    <input
      type={props.type}
      autocomplete="off"
      spellcheck={false}
      value={props.value}
      placeholder={props.placeholder}
      onInput={(event) => props.onInput(event.currentTarget.value)}
    />
  </label>
)
