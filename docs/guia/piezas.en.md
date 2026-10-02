# Pieces — building the agent {#piezas}

Everything you give the agent is a **piece** in the Room. Pieces live in
**closets**: small, pinned to the piece, nested and progressive. The first level
shows the minimum —what it is, its state, one action— and "more" expands. Nothing
is ever dumped flat.

## Piece types {#tipos}

- **Door (connector):** a door to an app. When you connect it —OAuth or key— its
  real tools drop into the scene.
- **Tool:** what the agent does. It can read from the world, send to the world, or
  process.
- **Gate (permission lock):** it stops and asks for your OK before touching
  outside. That **can't be auto-approved** with any setting.
- **Context / knowledge:** the agent's skills, recipes, memory and log.

A piece's chat, knobs and code **write the same thing**: three ways of touching
the same configuration.

## Choosing the team {#equipo}

Tell it above, in your own words, what you want it to do. As you type, the
closets that suit it light up. Look at the ones marked "suits you", or open any
and explore. Your agent can also **coordinate specialized helpers**: add the ones
it needs.

## What a piece's state tells you {#estado}

Tap a piece and its actions open **in an arc around it**. At the foot of the arc
there's one line saying how that piece is doing. Five states, and nothing else:

- 🟢 **Verified** — it really ran against the server and it worked. It says when.
- 🟡 **Untested** — it's in place, but nobody has tested it yet. Tap **Test**.
- 🔴 **Broken** — it was tested and it failed. Next to it goes the cause: your
  key is missing, your connection is down, the provider returned an error… The
  cause says **whose fault it is**, so you don't go checking your WiFi when the
  problem is a key.
- ⚪ **Not set up** — it's missing the account or key it needs to be testable.
- 🔒 **Premium** — your plan doesn't cover it.

**Test** and **Test again** are the same button: when the piece is red it changes
its name, so you can read it as a retry. You will never find two different buttons
for the same thing.

If the retry fails again, the arc stops offering you a repeat and opens **the
path** instead: the concrete steps to fix that piece. A button that leaves you in
the same place twice does not exist in the Room.

The raw server error is **always** available, folded under the state line. We
neither hide it nor summarize it: the cause tells you what kind of failure it is,
the raw text tells you what the machine actually answered.

## The lock and permissions {#candado}

Nothing that reaches the world is active yet. If you add email or messages, they
show up in the permissions list — and they **always** ask you first.

The lock is drawn **on the cable** that runs from the piece to the Core: one per
piece, glued to the cable, at the point everything that piece does passes through.
That's where it stops.

It only shows up on pieces that **touch the outside** — send, pay, publish, write.
A piece that only reads (medical images, papers, public catalogs) carries no lock,
and none is offered to you either: there is nothing to stop.

Tap it and it tells you the four things you need in order to decide: **what it
stops**, with which **rule** (always · once · remove), **how many times** it has
already stopped something, and where to see the decisions you've made.

**Removing the lock is not a free pass.** Even with it off, the engine still holds
back anything that moves **money** and anything that **sends** things to other
people. That floor doesn't go down with any setting.

## The plan, before you bring it to life {#plan}

Before saving, look at the plan: the **steps in order**, which closet each one
uses, and where it stops to ask for your OK. You approve it and only then does it
start. As it runs, it checks off steps and **stops only where something reaches
the world**. When it's done, whatever reached the world went through your OK.

## Review before equipping {#revisar}

When you inspect a piece of software, before anything is equipped we show you
**what it will be able to do**: the list of real tools read from the server, each
with a checkbox and **all of them ticked**. You tap **Continue** and exactly that
gets equipped. Unticking is optional: whatever you untick doesn't go in.

These are the **real tools Motor B read from the server** — zero placeholders.
Whatever you untick doesn't go into the MCP that gets sealed; the rest is
equipped exactly as-is. The panel shows which server they came from.

There is no mode to turn on — the list shows up on its own, always. The raw
detail of the forge (what was proposed, what the engine validated) lives in the
`</>` evidence.

## Still read-only {#solo-lectura}

A piece's Chat, Options and Code arrive in the next phase; today a piece is
read-only. (See `cuarto.en.md`.)
