# Open CoDesign — frontera de importación

**Origen:** https://github.com/OpenCoworkAI/open-codesign  
**Commit:** `b94d7156bf4aeb2c79892c91dc9934911a4e3741`  
**Licencia:** MIT (`LICENSE:1-21`)  
**Fecha:** 2026-08-09

## Unidad importada

Entró el repositorio completo rastreado por git, bajo `third_party/codesign/`, sin
historial ni `node_modules`. El testigo inmutable está fuera del worktree, en
`/tmp/gate4-diseno-testigo.O7318A`.

Antes de cualquier cirugía, los **818 archivos** del origen y del import tuvieron el
mismo digest SHA-256 de árbol:

```
1b01bd49d339f66af4321dfff799b3be4eabbfa2bab469664aef2c0042affc18
```

El digest concatena, por ruta ordenada, el SHA-256 de cada archivo y su nombre; por eso
cubre el árbol completo y no una muestra.

## Lo que no entra

No entraron `node_modules`, productos de build ni el historial git: son derivados
reproducibles o metadatos, no parte del árbol fuente rastreado. Las dependencias se
reinstalan desde `pnpm-lock.yaml`; el censo del estudio registró 967 paquetes únicos y
cero copyleft fuerte. JSZip se distribuye bajo su alternativa MIT.

## Artefacto transversal heredado para el ensamblado

El `aleph_sidecar.spec` exige el binario ya construido de Ciencia para no empaquetar una
Aleph que anuncie un workspace incapaz de arrancar. En esta rama el build de ese binario
no puede materializar sus dependencias con `bun install --frozen-lockfile`: Bun 1.3.14
requiere cambiar el lock upstream. El delta de lock documentado en `gate4-legal` aplica
a doc.haus, no a OpenScience; por ello se siguió exactamente su camino B.2, sin
redescubrir ni modificar ningún lockfile.

Se heredó de `gate4-legal` el binario certificado
`third_party/openscience/backend/cli/dist/@synsci/openscience-darwin-arm64/bin/openscience`.
SHA-256 fuente y destino verificados:

```
a0f0fd61c46b5e76b1b46c8b980972ae454f4bdc31766d3158cad7ec5edbd906
```

Asiento: **delta heredado de gate4-legal, causa: Bun 1.3.14 vs lock upstream**. Es un
derivado no rastreado de 127.613.568 bytes, sólo para que la app de esta rama se construya
con el mismo artefacto que Legal verificó contra dos sidecars instalados.

## Cirugía posterior, no confundida con la frontera

Después de esta marca bruta se extirpan OAuth ChatGPT/Codex, updater/release GitHub,
marca visible y los 25 `brand-refs` sin licencia individual. El delta contra el testigo
queda documentado en `EXTIRPACIONES.md`; la frontera de arriba no cambia.
