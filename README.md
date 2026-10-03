# Aleph

**One space. Infinite work.**

Aleph is a macOS workspace for bringing AI models, tools, and files together —
then using them across focused workspaces and reusable agents.

[⬇ Download Aleph 0.1.2 for macOS (Apple silicon)](https://github.com/josuecuguy1307/Aleph/releases/latest/download/Aleph-macOS-arm64.dmg)

[Website](https://aleph-site-jade.vercel.app/) ·
[Release notes](https://github.com/josuecuguy1307/Aleph/releases/tag/v0.1.2) ·
[Getting Started](docs/GETTING_STARTED.md)

### Install

#### macOS · Apple silicon

1. Download `Aleph-macOS-arm64.dmg`.
2. Open the downloaded DMG.
3. Drag **Aleph.app** to **Applications** in the window that opens.
4. Open **Aleph** from Applications.

<details>
<summary>If macOS blocks Aleph on first open</summary>

Aleph 0.1.2 is ad-hoc signed and not notarized, so macOS may ask you to approve
it. After trying to open it, go to **System Settings → Privacy & Security → Open
Anyway**. Only continue if you trust the download from this official release.
See [Apple's instructions](https://support.apple.com/102445).

</details>

<details>
<summary>Install with Homebrew</summary>

```sh
brew install --cask josuecuguy1307/tap/aleph
```

This installs the same Apple-silicon app and has the same first-open macOS
security prompt.

</details>

![Aleph brings Science, Education, Office, Finance, Legal, and Design into one workspace](assets/readme/workspaces-map.png)

## How to use Aleph

1. **Download and install on macOS.** Use the download button above, open the
   DMG, and move Aleph to Applications.
2. **Open Aleph.** Follow the setup prompts and choose your preferred language.
3. **Choose your model.** Connect an API provider or an installed, authenticated
   CLI provider such as Claude Code or Codex. Use your own provider access.
4. **Start in Home / La Sala.** Pick an agent, describe what you want to do, and
   work with the resulting files and artifacts.
5. **Open a specialized workspace:** Science, Education, Office, Finance, Legal,
   or Design — depending on the work in front of you.
6. **Make it your own in The Workshop / El Cuarto.** Compose agents, equip tools,
   and arrange workflows you can return to later.

Aleph is **model-agnostic**: available models depend on your installed providers,
authentication, and provider access limits. Local capabilities and connectors
may need explicit installation, configuration, or authorization before use.

[Continue with Getting Started →](docs/GETTING_STARTED.md)

## Your models. Your tools.

Bring the provider you want to use and connect the services your work needs.
Models, CLI agents, and connectors are separate capabilities — connecting one
does not automatically authorize the others.

| Models and CLI providers | Connected tools |
| --- | --- |
| ![Illustration of model APIs and CLI providers, including Claude Code and Codex](assets/readme/models-and-cli.png) | ![Illustration of connectors for communication, knowledge, files, and workflows](assets/readme/connect-tools.png) |

These illustrations show product concepts, not a guarantee that every integration
is ready on your machine. Availability depends on setup and permissions.
**Onshape remains optional / not certified.**

## Build from source

See [BUILDING.md](BUILDING.md) for prerequisites, the official build path, and
current reproducibility limitations.

## Open source

Aleph-owned source is licensed under [Apache-2.0](LICENSE). Third-party components
retain their own licenses; see [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES).

The **Aleph name, logo, mascot, and official branding** — including the product
imagery in this README — are covered separately by [TRADEMARKS.md](TRADEMARKS.md),
not granted by Apache-2.0. Forks may describe their origin factually, but must not
imply official status or endorsement. [Image provenance](assets/readme/README.md).

Want to contribute? Start with [CONTRIBUTING.md](CONTRIBUTING.md).

## Current release

**0.1.2** · [macOS installer and source release](https://github.com/josuecuguy1307/Aleph/releases/tag/v0.1.2)

The release page separates the macOS installer from the developer-only guest
assets. The exact guest kernel, root filesystem, and matching third-party source
bundle are also available there. [Guest asset details](deploy/guest/ASSETS.md)
and [compliance](deploy/guest/COMPLIANCE.md) remain available for developers;
full guest-image regeneration from source is not yet claimed.

The certified source baseline and snapshot scope are recorded in
[SOURCE_PROVENANCE.json](SOURCE_PROVENANCE.json). This README is the product-facing
introduction; the immutable `v0.1.2` tag preserves the original certified snapshot.
