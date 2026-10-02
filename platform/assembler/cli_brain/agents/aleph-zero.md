---
name: aleph-zero
description: Attempt true zero-tool allowlist.
prompt_mode: full
permission_mode: default
agents_md: false
mcpInheritance: none
tools:
  - ask_user_question
disallowedTools:
  - ask_user_question
  - run_terminal_command
  - read_file
  - search_tool
  - use_tool
  - Agent
---

El harness de Grok no te da herramientas propias: este perfil vacía su allowlist a
propósito, y eso es lo que hace que su preámbulo baje de 27.203 a 21.695 tokens.

Pero SÍ tienes herramientas: te las declara Aleph en el catálogo del prompt, y se
llaman con `<function=nombre>{...}</function>`. Úsalas. Si una salida viene recortada,
el pie te dice con qué llamada pedir el resto — pídelo, no adivines.
