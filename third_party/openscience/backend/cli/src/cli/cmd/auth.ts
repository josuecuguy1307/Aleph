import { Auth } from "../../auth"
import { cmd } from "./cmd"
import * as prompts from "@clack/prompts"
import { UI } from "../ui"
import { ModelsDev } from "../../provider/models"
import { map, pipe, sortBy, values } from "remeda"
import path from "path"
import os from "os"
import { Config } from "../../config/config"
import { Global } from "../../global"
import { managedApiBase } from "../../endpoints"
import { Plugin } from "../../plugin"
import { Instance } from "../../project/instance"
import { OpenScience } from "../../openscience"
import { Log } from "../../util/log"
import { runLocalModelSetup } from "./local"
import type { Hooks } from "@synsci/plugin"

const log = Log.create({ service: "cmd.logout" })

type PluginAuth = NonNullable<Hooks["auth"]>

/**
 * Handle plugin-based authentication flow.
 * Returns true if auth was handled, false if it should fall through to default handling.
 */
async function handlePluginAuth(
  plugin: { auth: PluginAuth },
  provider: string,
  options?: { filterMethods?: (method: PluginAuth["methods"][number]) => boolean },
): Promise<boolean> {
  const candidates = options?.filterMethods
    ? plugin.auth.methods
        .map((m, i) => ({ method: m, originalIndex: i }))
        .filter((x) => options.filterMethods!(x.method))
    : plugin.auth.methods.map((m, i) => ({ method: m, originalIndex: i }))

  if (candidates.length === 0) return false

  let index = candidates[0].originalIndex
  if (candidates.length > 1) {
    // Non-interactive shell (CI/piped): can't render a select, and a browser
    // loopback flow won't work either — auto-pick a device-code method if one is
    // offered so headless sign-in isn't a dead end.
    if (!process.stdin.isTTY) {
      const device = candidates.find((x) => /device/i.test(x.method.label))
      index = (device ?? candidates[0]).originalIndex
    } else {
      const method = await prompts.select({
        message: "Login method",
        options: candidates.map((x) => ({
          label: x.method.label,
          value: x.originalIndex.toString(),
        })),
      })
      if (prompts.isCancel(method)) throw new UI.CancelledError()
      index = parseInt(method)
    }
  }
  const method = plugin.auth.methods[index]

  // Handle prompts for all auth types
  await Bun.sleep(10)
  const inputs: Record<string, string> = {}
  if (method.prompts) {
    for (const prompt of method.prompts) {
      if (prompt.condition && !prompt.condition(inputs)) {
        continue
      }
      if (prompt.type === "select") {
        const value = await prompts.select({
          message: prompt.message,
          options: prompt.options,
        })
        if (prompts.isCancel(value)) throw new UI.CancelledError()
        inputs[prompt.key] = value
      } else {
        const value = await prompts.text({
          message: prompt.message,
          placeholder: prompt.placeholder,
          validate: prompt.validate ? (v) => prompt.validate!(v ?? "") : undefined,
        })
        if (prompts.isCancel(value)) throw new UI.CancelledError()
        inputs[prompt.key] = value
      }
    }
  }

  if (method.type === "oauth") {
    let authorize: Awaited<ReturnType<typeof method.authorize>>
    try {
      authorize = await method.authorize(inputs)
    } catch (e) {
      // e.g. the OAuth listener port is in use — surface a clean line, not a stack.
      prompts.log.error(e instanceof Error ? e.message : "Couldn't start sign-in.")
      prompts.outro("Not signed in")
      return true
    }

    if (authorize.url) {
      prompts.log.info("Go to: " + authorize.url)
    }

    if (authorize.method === "auto") {
      if (authorize.instructions) {
        prompts.log.info(authorize.instructions)
      }
      const spinner = prompts.spinner()
      spinner.start("Waiting for authorization...")
      try {
        const result = await authorize.callback()
        if (result.type === "failed") {
          spinner.stop("Sign-in wasn't completed", 1)
          prompts.log.info("Declined, timed out, or cancelled. Retry with `openscience keys signin`.")
        } else if (result.type === "success") {
          const saveProvider = result.provider ?? provider
          if ("refresh" in result) {
            const { type: _, provider: __, refresh, access, expires, ...extraFields } = result
            await Auth.set(saveProvider, {
              type: "oauth",
              refresh,
              access,
              expires,
              ...extraFields,
            })
          }
          if ("key" in result) {
            await Auth.set(saveProvider, {
              type: "api",
              key: result.key,
            })
          }
          spinner.stop("Login successful")
        }
      } catch (e) {
        // A thrown callback (denied consent, CSRF, timeout, network) must not
        // leave the spinner spinning or bubble a raw stack to the user.
        spinner.stop("Sign-in failed", 1)
        prompts.log.error(e instanceof Error ? e.message : "Unknown error")
      }
    }

    if (authorize.method === "code") {
      const code = await prompts.text({
        message: "Paste the authorization code here: ",
        validate: (x) => (x && x.length > 0 ? undefined : "Required"),
      })
      if (prompts.isCancel(code)) throw new UI.CancelledError()
      const result = await authorize.callback(code)
      if (result.type === "failed") {
        prompts.log.error("Failed to authorize")
      }
      if (result.type === "success") {
        const saveProvider = result.provider ?? provider
        if ("refresh" in result) {
          const { type: _, provider: __, refresh, access, expires, ...extraFields } = result
          await Auth.set(saveProvider, {
            type: "oauth",
            refresh,
            access,
            expires,
            ...extraFields,
          })
        }
        if ("key" in result) {
          await Auth.set(saveProvider, {
            type: "api",
            key: result.key,
          })
        }
        prompts.log.success("Login successful")
      }
    }

    prompts.outro("Done")
    return true
  }

  if (method.type === "api") {
    if (method.authorize) {
      const result = await method.authorize(inputs)
      if (result.type === "failed") {
        prompts.log.error("Failed to authorize")
      }
      if (result.type === "success") {
        const saveProvider = result.provider ?? provider
        await Auth.set(saveProvider, {
          type: "api",
          key: result.key,
        })
        prompts.log.success("Login successful")
      }
      prompts.outro("Done")
      return true
    }
  }

  return false
}

export const KeysCommand = cmd({
  command: "keys",
  aliases: ["auth"],
  describe: "manage your own provider API keys (BYOK)",
  builder: (yargs) =>
    yargs
      .command(AuthLoginCommand)
      .command(AuthLogoutCommand)
      .command(AuthListCommand)
      .demandCommand(),
  async handler() {},
})

export const AuthListCommand = cmd({
  command: "list",
  aliases: ["ls"],
  describe: "list providers",
  async handler() {
    UI.empty()
    const authPath = path.join(Global.Path.data, "auth.json")
    const homedir = os.homedir()
    const displayPath = authPath.startsWith(homedir) ? authPath.replace(homedir, "~") : authPath
    prompts.intro(`Credentials ${UI.Style.TEXT_DIM}${displayPath}`)
    const results = Object.entries(await Auth.all())
    const database = await ModelsDev.get()

    for (const [providerID, result] of results) {
      const name = database[providerID]?.name || providerID
      prompts.log.info(`${name} ${UI.Style.TEXT_DIM}${result.type}`)
    }

    prompts.outro(`${results.length} credentials`)

    // Environment variables section
    const activeEnvVars: Array<{ provider: string; envVar: string }> = []

    for (const [providerID, provider] of Object.entries(database)) {
      for (const envVar of provider.env) {
        if (process.env[envVar]) {
          activeEnvVars.push({
            provider: provider.name || providerID,
            envVar,
          })
        }
      }
    }

    if (activeEnvVars.length > 0) {
      UI.empty()
      prompts.intro("Environment")

      for (const { provider, envVar } of activeEnvVars) {
        prompts.log.info(`${provider} ${UI.Style.TEXT_DIM}${envVar}`)
      }

      prompts.outro(`${activeEnvVars.length} environment variable` + (activeEnvVars.length === 1 ? "" : "s"))
    }
  },
})

/**
 * Classify the overloaded `keys add [url]` positional.
 *  - a full http(s) URL → a custom endpoint (auth via /.well-known/openscience)
 *  - a bare provider id (a-z, 0-9, hyphens; optional `@ai-sdk/` prefix stripped)
 *    → preselect that provider, skipping the picker
 *  - anything else (or absent) → neither; fall through to the interactive picker
 *
 * Keeps `keys add deepseek` from becoming `fetch("deepseek/.well-known/…")`,
 * the "fetch() URL is invalid" crash in #142.
 */
export function classifyKeyTarget(arg?: string): { endpointUrl?: string; preselect?: string } {
  if (!arg) return {}
  if (/^https?:\/\//i.test(arg)) return { endpointUrl: arg }
  const preselect = arg.replace(/^@ai-sdk\//, "").match(/^[0-9a-z-]+$/)?.[0]
  return preselect ? { preselect } : {}
}

export const AuthLoginCommand = cmd({
  command: ["add [url]", "login [url]"],
  describe: "add a provider API key (BYOK)",
  builder: (yargs) =>
    yargs.positional("url", {
      describe: "openscience auth provider",
      type: "string",
    }),
  async handler(args) {
    await Instance.provide({
      directory: process.cwd(),
      async fn() {
        UI.empty()
        prompts.intro("Add credential")

        // The positional is overloaded: a full http(s) URL means a custom
        // endpoint that advertises its auth via /.well-known/openscience, while
        // a bare token (e.g. `keys add deepseek`) is a provider id to preselect.
        // Previously ANY positional went to the well-known fetch, so a provider
        // name became `fetch("deepseek/.well-known/openscience")` → the
        // "fetch() URL is invalid" crash from #142.
        const { endpointUrl, preselect } = classifyKeyTarget(args.url)
        if (args.url && !endpointUrl && !preselect) {
          prompts.log.warn(`"${args.url}" is neither a URL nor a valid provider id — choose a provider below.`)
        }

        if (endpointUrl) {
          const wellknown = await fetch(`${endpointUrl}/.well-known/openscience`).then((x) => x.json() as any)
          prompts.log.info(`Running \`${wellknown.auth.command.join(" ")}\``)
          const proc = Bun.spawn({
            cmd: wellknown.auth.command,
            stdout: "pipe",
          })
          const exit = await proc.exited
          if (exit !== 0) {
            prompts.log.error("Failed")
            prompts.outro("Done")
            return
          }
          const token = await new Response(proc.stdout).text()
          await Auth.set(endpointUrl, {
            type: "wellknown",
            key: wellknown.auth.env,
            token: token.trim(),
          })
          prompts.log.success("Logged into " + endpointUrl)
          prompts.outro("Done")
          return
        }
        await ModelsDev.refresh().catch(() => {})

        const config = await Config.get()

        const disabled = new Set(config.disabled_providers ?? [])
        const enabled = config.enabled_providers ? new Set(config.enabled_providers) : undefined

        const providers = await ModelsDev.get().then((x) => {
          const filtered: Record<string, (typeof x)[string]> = {}
          for (const [key, value] of Object.entries(x)) {
            if ((enabled ? enabled.has(key) : true) && !disabled.has(key)) {
              filtered[key] = value
            }
          }
          return filtered
        })

        const priority: Record<string, number> = {
          synsci: 0,
          anthropic: 1,
          "github-copilot": 2,
          openai: 3,
          google: 4,
          openrouter: 5,
          vercel: 6,
        }
        // A preselected provider id (bare positional) skips the picker and goes
        // straight to that provider's auth path, so `keys add deepseek` works.
        const specialIds = new Set([
          "openai-codex",
          "local",
          "other",
          "amazon-bedrock",
          "synsci",
          "vercel",
          "cloudflare",
          "cloudflare-ai-gateway",
        ])
        let provider: string | symbol | undefined = preselect
        if (preselect && !providers[preselect] && !specialIds.has(preselect)) {
          prompts.log.warn(
            `${preselect} isn't in the model catalog — the key will be stored, but you'll need to configure the provider in openscience.json. See the docs.`,
          )
        }
        if (!provider) {
          provider = await prompts.autocomplete({
            message: "Select provider",
            maxItems: 8,
            options: [
              // (Acá encabezaba la opción "Sign in with ChatGPT (Codex)". Salió con
              // el camino Codex.)
              // Local models aren't in the models.dev catalog — surface them at the
              // top so pointing OpenScience at Ollama / LM Studio / any local
              // OpenAI-compatible endpoint is a first-class, discoverable choice.
              {
                value: "local",
                label: "Local model (Ollama / LM Studio / OpenAI-compatible)",
                hint: "an endpoint on your machine — free, offline, no API key",
              },
              ...pipe(
                providers,
                values(),
                sortBy(
                  (x) => priority[x.id] ?? 99,
                  (x) => x.name ?? x.id,
                ),
                map((x) => ({
                  label: x.name,
                  value: x.id,
                  hint: {
                    synsci: "Atlas — recommended",
                    anthropic: "Claude Max or API key",
                    openai: "API key (to sign in with Codex/ChatGPT, use the option above)",
                  }[x.id],
                })),
              ),
              {
                value: "other",
                label: "Other",
              },
            ],
          })
        }

        if (prompts.isCancel(provider)) throw new UI.CancelledError()

        // Local endpoint (Ollama / LM Studio / OpenAI-compatible): runs the local
        // setup wizard, which writes a provider config block (not an auth key).
        if (provider === "local") {
          await runLocalModelSetup({ intro: false })
          return
        }

        // (Elegir "openai" abría acá una bifurcación entre suscripción de ChatGPT
        // (Codex OAuth) y llave de OpenAI Platform. Salió con el camino Codex: queda
        // sólo la llave, que cae directo al prompt de contraseña de abajo.)

        const plugin = await Plugin.list().then((x) => x.find((x) => x.auth?.provider === provider))
        if (plugin && plugin.auth) {
          const handled = await handlePluginAuth({ auth: plugin.auth }, provider)
          if (handled) return
        }

        if (provider === "other") {
          provider = await prompts.text({
            message: "Enter provider id",
            validate: (x) => (x && x.match(/^[0-9a-z-]+$/) ? undefined : "a-z, 0-9 and hyphens only"),
          })
          if (prompts.isCancel(provider)) throw new UI.CancelledError()
          provider = provider.replace(/^@ai-sdk\//, "")
          if (prompts.isCancel(provider)) throw new UI.CancelledError()

          // Check if a plugin provides auth for this custom provider
          const customPlugin = await Plugin.list().then((x) => x.find((x) => x.auth?.provider === provider))
          if (customPlugin && customPlugin.auth) {
            const handled = await handlePluginAuth({ auth: customPlugin.auth }, provider)
            if (handled) return
          }

          prompts.log.warn(
            `This only stores a credential for ${provider} - you will need to configure it in openscience.json, check the docs for examples.`,
          )
        }

        if (provider === "amazon-bedrock") {
          prompts.log.info(
            "Amazon Bedrock authentication priority:\n" +
              "  1. Bearer token (AWS_BEARER_TOKEN_BEDROCK or /connect)\n" +
              "  2. AWS credential chain (profile, access keys, IAM roles, EKS IRSA)\n\n" +
              "Configure via openscience.json options (profile, region, endpoint) or\n" +
              "AWS environment variables (AWS_PROFILE, AWS_REGION, AWS_ACCESS_KEY_ID, AWS_WEB_IDENTITY_TOKEN_FILE).",
          )
        }

        if (provider === "synsci") {
          prompts.log.info("Create an API key at https://app.syntheticsciences.ai/cli")
        }

        if (provider === "vercel") {
          prompts.log.info("You can create an api key at https://vercel.link/ai-gateway-token")
        }

        if (["cloudflare", "cloudflare-ai-gateway"].includes(provider)) {
          prompts.log.info(
            "Cloudflare AI Gateway can be configured with CLOUDFLARE_GATEWAY_ID, CLOUDFLARE_ACCOUNT_ID, and CLOUDFLARE_API_TOKEN environment variables. Read more: https://syntheticsciences.ai/docs/providers/#cloudflare-ai-gateway",
          )
        }

        const key = await prompts.password({
          message: "Enter your API key",
          validate: (x) => (x && x.length > 0 ? undefined : "Required"),
        })
        if (prompts.isCancel(key)) throw new UI.CancelledError()
        await Auth.set(provider, {
          type: "api",
          key,
        })

        prompts.outro("Done")
      },
    })
  },
})

// (Acá vivía el camino Codex del CLI: backendHasCodex, runCodexAuthFlow,
// AuthCodexCommand (`keys signin` / `keys codex`), disconnectCodexBackend y los
// comandos ConnectCommand / DisconnectCommand. Salieron enteros: el plugin que los
// servía usaba el client_id del Codex CLI oficial de OpenAI y, con sesión Atlas,
// subía los tokens de ChatGPT al backend del fabricante. El cerebro es Aleph.)

export const AuthLogoutCommand = cmd({
  command: ["remove", "rm", "logout"],
  describe: "remove a saved provider key",
  async handler() {
    UI.empty()
    const credentials = await Auth.all().then((x) => Object.entries(x))
    prompts.intro("Remove credential")
    if (credentials.length === 0) {
      prompts.log.error("No credentials found")
      return
    }
    const database = await ModelsDev.get()
    const providerID = await prompts.select({
      message: "Select provider",
      options: credentials.map(([key, value]) => ({
        label: (database[key]?.name || key) + UI.Style.TEXT_DIM + " (" + value.type + ")",
        value: key,
      })),
    })
    if (prompts.isCancel(providerID)) throw new UI.CancelledError()
    await Auth.remove(providerID)
    // (Acá borrar la credencial de Codex además la revocaba en el backend del
    // fabricante, con revokeCodexOnBackend. Salió con el camino Codex.)
    prompts.outro("Logout successful")
  },
})
