# Connect (Conectar) {#conectar}

Your agent uses what you give it access to. Some things already work on their own;
others ask you to connect your account — you decide, it's stored encrypted, and
you remove it whenever you want.

## The permission is yours {#permiso}

When a connector needs your account, we take you to the provider so you can
**authorize your own account**. The permission is yours and you revoke it whenever
you want. If you haven't signed in yet, we store your connection under a demo
account (encrypted all the same); in the product it stays in your account.

## The four connection families {#familias}

1. **Keyless:** it just works, no credentials.
2. **Data / key:** you paste an API key and it's ready. The key is stored
   encrypted in your vault; we don't ask for it before you pick the model or the
   connector.
3. **OAuth (browser):** it opens the provider's tab for you to authorize.
4. **Guided token:** we take you to create a new key at the provider and tell you
   exactly what to check. Copy the full key: many providers (Zotero, for example)
   show it only once.

## The catalog: search before forging {#catalogo}

The catalog blends **internal** connectors (ready) and **public registry** ones.
Badges tell the truth about each: `ready · no key`, `connected · ready`,
`ready · connect your account`, `community · unverified`. Type a name or category
to also search the public registry.

When you pick a connector, it is **validated** before connecting:

- **Verified as official:** you can connect safely.
- **Unverified** (no ownership proof): connect only if you trust the source.
- **Unknown:** the registry doesn't know that service. You can **build an MCP**
  from your API or your docs.

If the public catalog doesn't respond, we show only the internal connectors and
ask you to retry — **we don't invent results** or forge anything blindly.

## Watch out for the impostor {#impostor}

If the verified official connector differs from the one you picked, we warn you
and suggest connecting **the verified one**. Verification is against the real
owner of the service, not against the name.

## Building an MCP with Motor B {#motor-b}

If no connector exists for what you need, **Motor B** builds it from your API or
your docs and **validates it live**: it opens it, reads its real tools and leaves
them as equippable pieces in your Room. No theater — if it doesn't connect, it
tells you. You approve before equipping it.
