# Getting started with Aleph

Aleph brings your models, tools, and files into one desktop workspace. You do not
need to build an agent before you can start using it.

## Install and open

Download the [Aleph 0.1.2 macOS installer](https://github.com/josuecuguy1307/Aleph/releases/latest/download/Aleph-macOS-arm64.dmg).
This release is for **Apple silicon (arm64)**.

1. Open the downloaded DMG.
2. Drag **Aleph.app** to **Applications** in the DMG window.
3. Open **Aleph** from Applications and follow its setup prompts.

Aleph 0.1.2 is ad-hoc signed and not notarized. If macOS blocks the first open,
try opening the app once, then use **System Settings → Privacy & Security → Open
Anyway**. See [Apple's instructions](https://support.apple.com/102445). Only
continue if you trust the download from the official Aleph release.

Do not use the guest kernel or root filesystem release assets as the macOS
application installer. Developers who want to build their own copy should use
[BUILDING.md](../BUILDING.md).

Homebrew users can install the same release with
`brew install --cask josuecuguy1307/tap/aleph`; the first-open macOS security
prompt still applies.

## Connect a model

Open the model selector and choose the provider you want to use:

- **API access:** configure your own provider credentials where requested.
- **CLI access:** install the relevant CLI, authenticate it, and select it in
  Aleph. Claude Code and Codex are examples of CLI provider paths.

Aleph is model-agnostic. An option appearing in the selector does not mean that
the provider is installed, authenticated, or has current execution access.
Provider subscriptions, access permissions, and usage limits still apply.

## Start working

Use **Home** to navigate and **La Sala** to work with an agent: describe your task,
review what happens, and open the files or artifacts produced along the way.

For domain-focused work, choose a specialized workspace:

| Workspace | Focus |
| --- | --- |
| Science | Research and scientific work |
| Education | Study and learning |
| Office | Documents and productivity |
| Finance | Financial analysis |
| Legal | Legal documents and organized review |
| Design | Visual and creative work |

Workspace entry points share Aleph's shell. The tools available inside them
depend on the installed build, your provider, and any required integrations.

## Compose in The Workshop / El Cuarto

Use **The Workshop** (English) or **El Cuarto** (Spanish) to compose your agent:
choose its model, define its identity and goal, and equip the tools its work needs.
Save the agent so you can return to it, then use it in La Sala.

## Connect tools deliberately

Some capabilities need a locally installed program; others need an API key,
OAuth authorization, or additional setup. Follow the connector's setup flow and
check its test result before relying on it. Authorizing a model does not authorize
your other accounts or services.

Do not put credentials in source files or share private account/session data.
**Onshape is optional / not certified.**

[Back to Aleph](../README.md) · [Source release](https://github.com/josuecuguy1307/Aleph/releases/tag/v0.1.2)
