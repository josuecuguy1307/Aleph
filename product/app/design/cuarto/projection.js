/* projection.js — CAPA DE PROYECCIÓN del Cuarto (Fase 2 · 5 átomos + composición).
 *
 * Decisión 2: la receta puppets.config v1 es la FUENTE DE VERDAD; los bloques del diorama
 * son su PROYECCIÓN. Acá vive el contrato bloques ⇄ receta, en ambos sentidos:
 *   canvasToRecipe(state)            → config v1 (con belt.belt_refs[] = composición dinámica)
 *   recipeToCanvas(config, catalog)  → state (rehidrata el diorama desde una receta guardada)
 *
 * El bloque `canvas` (presentación pura) lo IGNORA el motor; sirve para volver a dibujar.
 */
window.Projection = (function () {
  const MODEL_BASE = { base_url: "https://api.groq.com/openai/v1", temperature: 0, max_tokens: 700, max_turns: 8 };
  // One human-name boundary shared by the renderer and this projection. It lives
  // in this already-shipped asset so incremental desktop updates cannot miss it.
  if (!window.AlephAgentIdentity) {
    const FALLBACK = "Agente sin nombre";
    const TECHNICAL = /^(?:(?:agent|agt|puppet)[-_])?[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$|^\d+(?:[-_./]\d+)*$|^(?:agent|puppet)[-_]?\d+$|^[0-9a-f]{20,}$|^(?:aleph|agent|puppet)\s+[\w-]*\s+[0-9a-f]{6,}$|(?:^|\/)(?:agent[-_])?[^/]+\.(?:config\.)?json$/i;
    const humanName = (value) => {
      const name = typeof value === "string" ? value.trim().replace(/\s+/g, " ") : "";
      return name && !TECHNICAL.test(name) ? name : null;
    };
    const displayName = (...values) => values.map(humanName).find(Boolean) || FALLBACK;
    const nameOfPuppet = (puppet) => displayName(puppet && puppet.name,
      puppet && puppet.config && puppet.config.meta && puppet.config.meta.name);
    window.AlephAgentIdentity = Object.freeze({ FALLBACK, humanName, displayName, nameOfPuppet });
  }
  // picker amigable → modelo real (sin jerga en pantalla; acá traducimos)
  const MODELS = {
    equilibrado: { primary: "llama-3.3-70b-versatile", fallback: "openai/gpt-oss-20b" },
    veloz:       { primary: "openai/gpt-oss-20b",      fallback: "llama-3.1-8b-instant" },
    potente:     { primary: "openai/gpt-oss-120b",     fallback: "llama-3.3-70b-versatile" },
  };

  function _modelFor(key) {
    const m = MODELS[key] || MODELS.equilibrado;
    return Object.assign({}, MODEL_BASE, m);
  }

  // ── AGENTE ANIDADO (paso 5 · costura del Cuarto) ────────────────────────────
  // Una pieza-AGENTE (un recinto con Núcleo adentro, o marcada atom "agente") representa un
  // SUB-AGENTE: su ref va a belt.agent_refs[], NUNCA a belt_refs[]. La distinción cae del
  // Núcleo real: con Núcleo = sub-agente (genera agent_ref); SIN Núcleo = cajón = scoping
  // visual (no genera agent_ref — sus tools suben por las piezas-tool de adentro, normales).
  // REGLA LOAD-BEARING (paso 1): un agent_ref filtrado a belt_refs[] hace que el motor lo
  // cargue como belt y muera en silencio. Por eso `_isAgentPiece` EXCLUYE al agente del
  // camino de tools — aunque por error trajera atom "tool" junto con su Núcleo.
  function _isAgentPiece(b) {
    return !!b && (b.atom === "agente" || !!b.nucleo);
  }

  // ── bloques del diorama → receta v1 ─────────────────────────────────────────
  function _agentDisplayName() {
    const identity = window.AlephAgentIdentity;
    if (identity && typeof identity.displayName === "function") return identity.displayName.apply(null, arguments);
    // Legacy builders and focused tests can run projection.js by itself.
    const technical = /^(?:(?:agent|agt|puppet)[-_])?[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$|^\d+(?:[-_./]\d+)*$|^(?:agent|puppet)[-_]?\d+$|^[0-9a-f]{20,}$|^(?:aleph|agent|puppet)\s+[\w-]*\s+[0-9a-f]{6,}$|(?:^|\/)(?:agent[-_])?[^/]+\.(?:config\.)?json$/i;
    for (let i = 0; i < arguments.length; i++) {
      const value = typeof arguments[i] === "string" ? arguments[i].trim().replace(/\s+/g, " ") : "";
      if (value && !technical.test(value)) return value;
    }
    return "Agente sin nombre";
  }

  function _agentNameByRef(agents) {
    const names = {};
    (agents || []).forEach((agent) => {
      if (!agent || !agent.id) return;
      const ref = "catalog/agents/agent-" + agent.id + ".config.json";
      const meta = agent.config && agent.config.meta;
      names[ref] = _agentDisplayName(agent.name, meta && meta.name);
    });
    return names;
  }

  function canvasToRecipe(state) {
    state = state || {};
    const nucleo = state.nucleo || {};
    const blocks = state.blocks || [];
    const agentish = blocks.filter(_isAgentPiece);
    // toolish EXCLUYE a los agentes: el ref de un sub-agente jamás cae en el camino de belt_refs.
    const toolish = blocks.filter((b) => !_isAgentPiece(b) && (b.atom === "tool" || b.atom === "conexion"));

    // belt_refs = unión de los belt_ref de las piezas-tool (orden estable, sin duplicar)
    const belt_refs = [];
    const tf = {};
    const keys = {};
    const tool_aliases = {};
    toolish.forEach((b) => {
      const internal = Array.isArray(b.servers) ? b.servers : [];
      if (internal.length) {
        internal.forEach((server) => {
          const beltRef = server.belt_ref;
          const name = server.name || server.server;
          if (beltRef && belt_refs.indexOf(beltRef) === -1) belt_refs.push(beltRef);
          if (name) {
            tf[name] = (tf[name] || []).concat(server.tools || []);
            tool_aliases[name] = Object.assign(
              {}, tool_aliases[name] || {}, server.tool_aliases || {}
            );
          }
          // El proveedor que lee el proceso puede ser un alias técnico (FeedOracle);
          // el secreto SIEMPRE se resuelve desde la credencial de la entidad (FRED).
          const binding = server.credential_binding || {};
          const runtimeProvider = binding.runtime_provider || server.connector;
          const credentialProvider = binding.credential_provider
            || server.credential_provider
            || (b.credential && b.credential.provider);
          if (runtimeProvider && credentialProvider)
            keys[runtimeProvider] = { byok_ref: "keys:" + credentialProvider };
        });
      } else {
        if (b.belt_ref && belt_refs.indexOf(b.belt_ref) === -1) belt_refs.push(b.belt_ref);
        if (b.ref) { tf[b.ref] = (tf[b.ref] || []).concat(b.tools || []); }
      }
      (b.belt_refs || []).forEach((ref) => {
        if (ref && belt_refs.indexOf(ref) === -1) belt_refs.push(ref);
      });
      // las conexiones (token/oauth) entran como BYOK por referencia (el broker inyecta)
      if (b.atom === "conexion" && b.connector) keys[b.connector] = { byok_ref: "keys:" + b.connector };
      if (b.credential && b.credential.provider)
        keys[b.credential.provider] = { byok_ref: "keys:" + b.credential.provider };
      // [reforma · a] un MCP plegado puede pedir VARIAS cuentas (un server, dos proveedores):
      // todas entran. La lista es superset de `connector`, así que una pieza vieja no cambia.
      // No pisar el enlace runtime→credencial canónica que armó `servers[]`.
      // FRED, por ejemplo, ejecuta un proceso que espera `feedoracle` pero la
      // persona guarda UNA sola credencial `fred`.
      (b.connectors || []).forEach((c) => {
        if (c && !keys[c]) keys[c] = { byok_ref: "keys:" + c };
      });
    });
    Object.keys(tf).forEach((s) => { tf[s] = Array.from(new Set(tf[s])); });

    // agent_refs = unión de los refs de las piezas-AGENTE (orden estable, sin duplicar).
    // SLUG/PATH del agente = b.agent_ref (canónico) o b.ref de respaldo. Una pieza-agente sin
    // ref no proyecta (no hay receta hija a la que apuntar).
    const agent_refs = [];
    agentish.forEach((b) => {
      const ref = b.agent_ref || b.ref;
      if (ref && agent_refs.indexOf(ref) === -1) agent_refs.push(ref);
    });
    // 2c · modelo PROPIO por sub-agente: slug ESPEJO de belt_resolver._slug_from_agent_ref
    // (basename sin .config.json/.json) — el runtime indexa child_models por ese slug.
    const child_models = {};
    agentish.forEach((b) => {
      const ref = b.agent_ref || b.ref;
      if (ref && b.child_model)
        child_models[String(ref).split("/").pop().replace(/\.config\.json$|\.json$/, "")] = _modelFor(b.child_model);
    });

    // contexto/memoria: si hay un bloque de contexto, la memoria queda activa
    const hasContexto = blocks.some((b) => b.atom === "contexto");

    const recipe = {
      schema_version: "v1",
      meta: {
        name: (nucleo.name || "Mi agente").trim(),
        nicho: nucleo.nicho || "general",
        descripcion: nucleo.descripcion || "",
      },
      model: _modelFor(nucleo.model),
      belt: {
        belt_refs: belt_refs.length ? belt_refs : ["platform/assembler/fixtures/belt-calc.mcp.json"],
        tool_filters: Object.keys(tf).length ? tf : {},
      },
      framing: { inline: "" },
      rag: { enabled: !!hasContexto, mode: "manual", dir: nucleo.rag_dir || null },
      keys: keys,
      gates: { money_touch: "needs_ok", send: "needs_ok" },
      canvas: {
        version: "v1",
        nucleos: [{ id: "nucleo", x: nucleo.x != null ? nucleo.x : 320, y: nucleo.y != null ? nucleo.y : 200, model: nucleo.model || "equilibrado", gridX: nucleo.gridX, gridY: nucleo.gridY }],
        blocks: blocks.map((b) => {
          const o = {
            id: b.id, atom: b.atom, card_id: b.card_id || b.id, ref: b.ref || null,
            zone: b.zone || "mesa", x: b.x || 0, y: b.y || 0, connector: b.connector || null,
            // iso presentation for the Pixi Cuarto (DOM diorama leaves these undefined)
            gridX: b.gridX, gridY: b.gridY,
          };
          // AGENTE ANIDADO: SÓLO una pieza-agente guarda agent_ref + nucleo en el canvas, para
          // que el round-trip la rehidrate como agente (y no como tool). Las piezas-tool quedan
          // BYTE-IDÉNTICAS (un canvas sin agentes proyecta exactamente el mismo canvas de hoy).
          if (_isAgentPiece(b)) {
            o.agent_ref = b.agent_ref || b.ref || null; o.nucleo = true;
            // El path/UUID sigue en agent_ref/card_id; la etiqueta es un dato distinto y
            // humano. Sin esto un reload reconstruía la cara desde card_id (= agent-UUID).
            o.label = _agentDisplayName(b.label);
            if (b.child_model) o.child_model = b.child_model;   // 2c · su modelo elegido sobrevive el round-trip
            // STEP 2·B2 · membresía del bus: SÓLO se serializa cuando está DESCONECTADO (false); el
            // default (conectado) queda undefined → un canvas sin desconexiones es byte-idéntico al de hoy.
            if (b.sharesMemory === false) o.sharesMemory = false;
          } else {
            // PIEZA-TOOL AUTO-DESCRIBIBLE (raíz de la "pieza muda"): el belt_ref y las tools de una
            // pieza FORJADA viven sólo en belt.belt_refs/tool_filters — el catálogo NO las tiene, así
            // que sin serializarlas EN el bloque, recipeToCanvas no puede recuperarlas al rehidratar
            // (`a` = {} para un server que no está en el catálogo) y el re-guardado emite tool_filters
            // VACÍO = pieza equipada pero MUDA (0 tools cableadas por LazyToolRegistry). Guardamos el
            // bloque completo: belt_ref + tools + label viajan con la pieza, sea de catálogo o forjada.
            // Para una pieza de catálogo es idempotente (el mismo dato que el atom ya trae).
            if (b.belt_ref) o.belt_ref = b.belt_ref;
            if (b.service) o.service = b.service;
            o.diorama_symbol = b.diorama_symbol || "generico";
            if (b.belt_refs && b.belt_refs.length) o.belt_refs = b.belt_refs.slice();
            if (b.servers && b.servers.length)
              o.servers = b.servers.map((server) => JSON.parse(JSON.stringify(server)));
            if (b.credential) o.credential = JSON.parse(JSON.stringify(b.credential));
            if (b.tools && b.tools.length) o.tools = b.tools.slice();
            if (b.label) o.label = b.label;
            // sólo si el MCP pliega más de una cuenta (una sola viaja en `connector`, como siempre)
            if (b.connectors && b.connectors.length > 1) o.connectors = b.connectors.slice();
          }
          return o;
        }),
        links: state.links || [],
      },
    };
    // STEP 4 · 4B · TERRITORIO default de La Sala (la lente de presentación con la que la Sala
    // narra el run). Vive en `canvas` — el motor la IGNORA por completo y el validator NO valida
    // canvas-inner → additivo, cero backend (un top-level `territorio` sería 422 por el allowlist
    // estricto). Condicional como agent_refs/memory: sin territorio elegido la receta es
    // BYTE-IDÉNTICA a la de hoy. Read-order en la Sala: canvas.territorio ?? meta.territorio ?? "general".
    if (nucleo.territorio) recipe.canvas.territorio = nucleo.territorio;
    // AGENTE ANIDADO: la clave belt.agent_refs[] SÓLO aparece si hay piezas-agente. Sin agentes,
    // la receta es byte-idéntica a la de hoy (no se agrega la clave). Convive con belt_refs[]:
    // un padre puede tener tools propias (belt_refs) Y sub-agentes (agent_refs) a la vez.
    if (agent_refs.length) recipe.belt.agent_refs = agent_refs;
    if (Object.keys(tool_aliases).length) recipe.belt.tool_aliases = tool_aliases;
    // 2c · SOLO si alguna pieza-agente eligió modelo propio (sin elección → receta byte-idéntica).
    if (Object.keys(child_models).length)
      recipe.belt.agent_policy = { child_model: "own", child_models };
    // 2c · MEMORIA · COMPARTIDA first-class: la pieza "memoria" baja al top-level recipe.memory
    // (el runtime la compone al padre Y a cada hijo con el MISMO archivo). Sin pieza → sin clave.
    // STEP 2·B2 · MEMBERS = identidades CONECTADAS al bus (la línea teal por-agente). El executor
    // matchea shared_self ('nucleo' | slug del hijo = belt_resolver._slug_from_agent_ref) contra
    // esta lista (o "*"). "nucleo" entra por default (el Núcleo comparte salvo _shareMemory:false);
    // cada pieza-agente entra por su SLUG salvo sharesMemory===false (desconectada del cilindro).
    // El backend acepta la lista explícita o "*"; emitimos la explícita para que la membresía sea
    // legible/serializable (y el round-trip la reconstruya). Sin pieza-memoria → recipe.memory ausente.
    if (blocks.some((b) => b.atom === "memoria")) {
      const members = [];
      if (nucleo._shareMemory !== false) members.push("nucleo");
      agentish.forEach((b) => {
        if (b.sharesMemory === false) return;                        // sub-agente desconectado del bus
        const ref = b.agent_ref || b.ref;
        if (!ref) return;
        const slug = String(ref).split("/").pop().replace(/\.config\.json$|\.json$/, "");
        if (members.indexOf(slug) === -1) members.push(slug);
      });
      recipe.memory = { shared: true, ref: "product/belts/memoria-compartida.mcp.json", members };
    }
    return recipe;
  }

  // ── receta guardada → bloques del diorama (rehidratar) ──────────────────────
  // `catalog` = array de átomos de /v1/atoms/catalog (para reconstruir label/tools/auth).
  function recipeToCanvas(config, catalog, agents) {
    config = config || {};
    catalog = catalog || [];
    const byServer = {}, byId = {};
    catalog.forEach((a) => {
      if (a.server) byServer[a.server] = a;
      (a.servers || []).forEach((server) => {
        if (server && (server.name || server.server))
          byServer[server.name || server.server] = a;
      });
      byId[a.id] = a;
      if (a.key) byId[a.key] = a;
    });
    // fallback de tools para una pieza cuyo bloque no las trae (receta guardada-bien-una-vez antes
    // del fix): belt.tool_filters está keyed por server (= b.ref), así que recupera las tools reales.
    const _tf = (config.belt && config.belt.tool_filters) || {};
    const agentNames = _agentNameByRef((agents && agents.length) ? agents : (window.__myPuppets || []));

    const cv = config.canvas || {};
    const nuc0 = (cv.nucleos && cv.nucleos[0]) || {};
    const nucleo = {
      name: (config.meta && config.meta.name) || "Mi agente",
      nicho: (config.meta && config.meta.nicho) || "general",
      descripcion: (config.meta && config.meta.descripcion) || "",
      model: nuc0.model || "equilibrado",
      x: nuc0.x, y: nuc0.y,
      rag_dir: (config.rag && config.rag.dir) || null,
      // STEP 4 · 4B · round-trip del territorio (canvas primero, meta como alterna); ausente → sin clave.
      territorio: cv.territorio || (config.meta && config.meta.territorio) || undefined,
    };

    let blocks = [];
    if (cv.blocks && cv.blocks.length) {
      // camino feliz: el canvas guardado tiene la disposición exacta
      blocks = cv.blocks.map((b) => {
        // AGENTE ANIDADO: una pieza-agente guardada (atom "agente" / con agent_ref / con Núcleo)
        // rehidrata como pieza-AGENTE — NO se busca en el catálogo de tools (no es una tool).
        if (_isAgentPiece(b) || b.agent_ref) {
          const aref = b.agent_ref || b.ref || null;
          return {
            id: b.id, atom: "agente", card_id: b.card_id || aref,
            label: _agentDisplayName(b.label, agentNames[aref]), agent_ref: aref, ref: aref,
            tools: [], zone: b.zone || "mesa", nucleo: true,
            child_model: b.child_model || null,   // 2c · el modelo propio rehidrata con la pieza
            sharesMemory: b.sharesMemory,         // STEP 2·B2 · membresía del bus (undefined = conectado por default)
            connector: null, x: b.x || 0, y: b.y || 0, gridX: b.gridX, gridY: b.gridY,
          };
        }
        if (b.atom === "memoria") {
          // 2c · la pieza de memoria compartida no es un átomo del catálogo: rehidrata por forma
          return { id: b.id, atom: "memoria", card_id: b.card_id || "memoria", label: "Memoria",
                   ref: null, tools: [], zone: b.zone || "mesa", connector: null,
                   x: b.x || 0, y: b.y || 0, gridX: b.gridX, gridY: b.gridY };
        }
        const a = byId[b.card_id] || byServer[b.ref] || {};
        if (a.servers && a.servers.length) {
          return {
            id: b.id, atom: a.atom || "tool", card_id: a.key || a.id,
            label: a.label || a.id, service: a.service || a.id, ref: null,
            diorama_symbol: a.diorama_symbol || b.diorama_symbol || "generico",
            tools: (a.tools || []).slice(), zone: b.zone || a.zone || "mesa",
            belt_refs: (a.belt_refs || []).slice(),
            servers: a.servers.map((server) => JSON.parse(JSON.stringify(server))),
            credential: a.credential ? JSON.parse(JSON.stringify(a.credential)) : null,
            connector: a.connector || null, connectors: (a.connectors || []).slice(),
            auth: a.auth || "keyless", x: b.x || 0, y: b.y || 0,
            gridX: b.gridX, gridY: b.gridY, category: a.category,
          };
        }
        // PIEZA-TOOL AUTO-DESCRIBIBLE: preferí lo que el BLOQUE guardó (una pieza FORJADA no está en
        // el catálogo → `a` = {}); caé a belt.tool_filters[ref] (receta guardada-bien-una-vez, sin
        // tools en el bloque) y recién después al catálogo (pieza de catálogo, o receta vieja pre-fix).
        // Sin esto, el re-guardado de una pieza forjada re-emite tools=[] → pieza equipada pero MUDA.
        const _tfTools = (b.ref && _tf[b.ref] && _tf[b.ref].length) ? _tf[b.ref] : null;
        return {
          id: b.id, atom: b.atom || a.atom || "tool", card_id: b.card_id,
          diorama_symbol: b.diorama_symbol || a.diorama_symbol || "generico",
          label: b.label || a.label || b.card_id || b.ref, ref: b.ref || a.server,
          tools: (b.tools && b.tools.length) ? b.tools : (_tfTools || a.tools || []),
          zone: b.zone || a.zone || "mesa",
          belt_ref: b.belt_ref || a.belt_ref, connector: b.connector || a.connector || null,
          connectors: b.connectors || a.connectors || undefined,
          auth: a.auth || "keyless", x: b.x || 0, y: b.y || 0,
          gridX: b.gridX, gridY: b.gridY, category: a.category,
        };
      });
    } else {
      // fallback: receta sin canvas → inferir bloques de tool_filters (servers → piezas)
      const tf = (config.belt && config.belt.tool_filters) || {};
      Object.keys(tf).forEach((srv) => {
        const a = byServer[srv] || {};
        if (a.servers && a.servers.length) {
          blocks.push({
            id: "blk-" + (a.service || a.id || srv), atom: a.atom || "tool",
            card_id: a.key || a.id, label: a.label || a.id || srv,
            service: a.service || a.id, ref: null, tools: (a.tools || []).slice(),
            diorama_symbol: a.diorama_symbol || "generico",
            zone: a.zone || "mesa", belt_refs: (a.belt_refs || []).slice(),
            servers: a.servers.map((server) => JSON.parse(JSON.stringify(server))),
            credential: a.credential ? JSON.parse(JSON.stringify(a.credential)) : null,
            connector: a.connector || null, connectors: (a.connectors || []).slice(),
            auth: a.auth || "keyless", x: 0, y: 0,
          });
          return;
        }
        blocks.push({
          id: "blk-" + srv, atom: a.atom || "tool", card_id: a.id || srv,
          diorama_symbol: a.diorama_symbol || "generico",
          label: a.label || srv, ref: srv, tools: tf[srv] || a.tools || [],
          zone: a.zone || "mesa", belt_ref: a.belt_ref, connector: a.connector || null,
          auth: a.auth || "keyless", x: 0, y: 0,
        });
      });
      // AGENTE ANIDADO: inferir piezas-AGENTE desde belt.agent_refs[] (simétrico a tool_filters).
      const agentRefs = (config.belt && config.belt.agent_refs) || [];
      const cmodels = (config.belt && config.belt.agent_policy && config.belt.agent_policy.child_models) || {};
      // STEP 2·B2 · sin canvas.blocks, la membresía se reconstruye de recipe.memory.members: un slug
      // AUSENTE (y sin "*") = desconectado del bus → sharesMemory:false; con "*" o presente = default.
      const _mMembers = (config.memory && Array.isArray(config.memory.members)) ? config.memory.members : null;
      const _connected = (slug) => !_mMembers || _mMembers.indexOf("*") !== -1 || _mMembers.indexOf(slug) !== -1;
      agentRefs.forEach((ref, i) => {
        const slug = String(ref).split("/").pop().replace(/\.config\.json$|\.json$/, "");
        blocks.push({
          id: "agt-" + (String(ref).replace(/[^a-zA-Z0-9_-]+/g, "-").replace(/^-+|-+$/g, "") || i),
          atom: "agente", card_id: ref, label: _agentDisplayName(agentNames[ref]), agent_ref: ref, ref: ref,
          child_model: cmodels[slug] ? (cmodels[slug].alias || null) : null,   // 2c · alias si viajó; el cfg completo vive en la receta
          sharesMemory: _connected(slug) ? undefined : false,   // STEP 2·B2 · membresía reconstruida de members
          tools: [], zone: "mesa", nucleo: true, connector: null, x: 0, y: 0,
        });
      });
      // 2c · memoria compartida first-class → la pieza vuelve al canvas
      if (config.memory && config.memory.shared)
        blocks.push({ id: "memoria", atom: "memoria", card_id: "memoria", label: "Memoria",
                      ref: null, tools: [], zone: "mesa", connector: null, x: 0, y: 0 });
    }
    const links = cv.links || blocks.map((b) => ({ from: b.id, to: "nucleo" }));
    return { nucleo, blocks, links };
  }

  return { canvasToRecipe, recipeToCanvas, MODELS, MODEL_BASE };
})();
