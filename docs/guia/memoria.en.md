# Memory {#memoria}

An agent is not a bare model: it remembers what it has been doing and what it
knows about you, between tasks. But **you** decide how much it carries and what
gets pinned.

## Remember or start fresh {#recordar}

- **Remembers between runs:** it keeps what it has been doing and what it knows
  about you, from one task to the next.
- **Starts fresh:** it saves nothing between tasks. Every run begins clean.

## Inheritance — what each copy carries {#herencia}

When you reuse or compose an agent, you decide what it **inherits**:

- **Only the expertise:** it operates from its expertise and what you asked it to
  remember; its self-learned experience from each run **does not accumulate**. It
  governs on every run and when you reuse or compose it.
- **Everything it knows:** it keeps everything it learns — expertise and
  experience.

In both cases, **account memory and anything confidential are never carried
over**. You save the agent to **pin** the chosen inheritance.

## Account memory — "About you" {#cuenta}

It is what your agents know about you. You review it and prune it whenever you
want. When an agent learns something about you, it **proposes it**: it doesn't
apply until your OK. You find it in the "About you" panel in the Room and also in
the Workroom. When you save it, your agents already know it; when you prune it, it
stops applying.

## The room's shared memory {#compartida}

In a room with several connected agents there is a **shared knowledge base**
(entities + relations) that they all read and write. It lives in the run's space;
sub-agents see it through the same real file. Each connected agent leaves its
contribution when it finishes. A piece can be **isolated**: it neither sees nor
leaves anything in that shared memory.

## Reference knowledge (RAG) {#rag}

These are documents the agent reads as **reference notes**, never as orders. The
index lives on your machine and the embeddings use **your** key.
