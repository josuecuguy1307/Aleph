# The Room (El Cuarto) {#cuarto}

The Room is the workshop where you build your agent. It is a living scene (a
diorama): everything you add shows up as a piece, and when you save, the agent
comes to life. This is where you decide **what** the agent is; in the Workroom
(La Sala) you **use** it.

## The Core — the agent {#nucleo}

The Core is the agent itself: its **model**, its **identity** and its
**goal**. It is what decides which piece to use at each moment and **re-decides
with every echo** (each result that comes back from the world). It is not a fixed
script: it reasons, picks a tool, looks at what happened, and picks again.

- **Identity and goal** are text you give it ("You are a clear, reliable
  assistant…", "finance analyst…", "office assistant…"). They set its tone and
  its working rules.
- The **active model is confirmed at run time**: if it degrades to a fallback
  model, the Workroom shows it. The truth about the model comes from execution,
  not from "the binary exists". (See `cerebros.en.md`.)

## The Core splits work — workers and the run plan {#workers}

When the Core declares a **plan**, that plan shows up in the run panel: the steps
in order and, for each one, whether it will **split**. A step marked to split
shows how many **workers** it opens.

Workers are **ephemeral** helpers: the Core opens them for a heavy stretch
—reading, extracting, counting across several sources— and they close when that
stretch ends. They appear in the workers panel and **only there**; they aren't
pieces of your agent and they aren't saved. If none are active, nothing is being
split right now.

Your plan sets how many can run **at a time**; the rest queue up.

## The zones and the MCP door {#zonas}

The scene is organized in zones: the **Core** (the agent), the **Connection**
(doors to real-world apps), the **Context** (what the agent knows). The **MCP
door** is how an app's tools get in: when you connect it —with OAuth or a key—
its real tools drop into the scene as equippable pieces.

## The flow lens {#lente}

The flow lens is a **derived view** of the build: it shows the order in which
pieces would activate. It **does not touch the build** — it just draws it another
way. Turning it on or off changes nothing you built.

## The session form {#sesion}

Each piece of software declares **how you get in**: open (no credential) · token ·
login (username and password) · browser with OAuth and 2FA. When there is 2FA,
**you provide the second factor** — the engine never solves a 2FA on its own.
(See `conectar.en.md`.)

## The evidence (dev mode) {#evidencia}

Dev mode shows the **raw technical evidence** of each Motor B step: the real
request, the real response, the raw MCP. It is hidden by default because what
matters —verification against the real environment— is already in plain sight.
You turn it on only when you want to audit the detail.

## The Guide in the Room {#guia}

The Guide is a hands-on copilot: it can look at and move the Room, open closets,
point at pieces and **open flows** for you. It has one line it **never crosses**:
it **proposes and opens, never completes** the action that reaches the world. To
act on the real world —send, pay, execute— the work moves to the Workroom, where
you give the OK. If you ask for something outside its reach, it tells you instead
of pretending it did it. (See `cerebros.en.md` for its model and its limits.)

## Pieces still read-only {#solo-lectura}

Chat, Options and Code for a piece arrive in an upcoming phase. Today a piece is
read-only: you can view it, not edit it from there. (See `piezas.en.md`.)

## My agents — what you saved {#mis-agentes}

"My agents" is the list of agents you saved to your account. Open one and you
pick up where you left off: the whole build comes back, every piece in its place.
If you haven't saved any yet the list is empty — build one in the Room and tap
**⤓ Save**.

## Where to start {#empezar}

The Room starts with just the Core. From there you have three paths, all in the
**⋯** menu on the bar:

- **＋ Equip** — add pieces from the catalog (the fastest way to start).
- **⌕ Inspect** — bring in software that isn't in the catalog yet: it gets
  inspected and its real tools land in the scene.
- **💬 Guide** — if you'd rather describe it in your own words and have it built.

Once there are pieces, the **▶ RUN** button puts them to work.

