# OfficeCLI: A — PROCEDENCIA LOCAL DEMOSTRADA

El ejecutable local intacto es idéntico byte a byte al asset oficial **v1.0.145**,
no v1.0.143. No se sustituyó, firmó ni parcheó ningún binario.

- Archivo distribuible: bin/officecli-macos-arm64.
- Asset: https://github.com/iOfficeAI/OfficeCLI/releases/download/v1.0.145/officecli-mac-arm64
- SHA256: d66763a563bc844c3cc67036ebc7c4a9caa9319b9592814d9acd3706da231fc1.
- Tamaño: 33764912 bytes.
- Release: https://github.com/iOfficeAI/OfficeCLI/releases/tag/v1.0.145
- Commit asociado al tag: e402d2853259177aba05ee6f79d38b7e1ff067ae.
- Tag anotado: 4104770e1add9f3b0726e0ca6ad6443dfa71bc4d, sin firma Git verificada.
- API oficial y SHA256SUMS publicados coinciden con el digest calculado del download
  y del local. UPSTREAM-IDENTITY.json conserva datos, URLs, hashes y pruebas.

La selección conserva exactamente el componente ya vendorizado y lo identifica como
distribución oficial1.0.145. La identidad del archivo completo incluye headers/load
commands, todas las secciones, UUID, bibliotecas declaradas, entitlements, firma y payload
gestionado/recursos; no se deduce de dos secciones aisladas.
Mach-O arm64; UUID EAEBC164-E13D-3F82-ACD3-FA6CABA77E27; min macOS12.0, SDK15.5;
Developer ID AionUi Inc. 52JQX2HUSC; allow-jit; codesign --verify --strict pasa.

## Corrección del bloqueo anterior

Local devuelve1.0.145 por CLI y MCP. MACHO-COMPARISON.json comparaba este local con
el release1.0.143 (digest2f158...): las16 secciones distintas son un resultado válido,
pero ese comparador pertenecía a otro release, no demuestra un origen local desconocido.
SHA459b1a473faf33f2f52e697ac6d265a3f67b176a declarado en el import es ancestro del
tag1.0.145, 22 commits atrás, no su commit. No identifica el build.
La comparación histórica se conserva. No se consultaron originales ni app instalada.

## Pruebas mínimas y protección

30 llamadas MCP por cada uno: local1.0.145, download oficial1.0.145 y oficial1.0.143.
Todos PASS: initialize/tools/list; carga skills/help; creación sintética DOCX/XLSX/PPTX;
edición, consulta, preservación de texto ajeno a la edición, eliminación de shape;
save, lectura, validate (cero errores en los tres formatos), integridad ZIP/OpenXML.
No es cobertura exhaustiva de merges/raw-set, auditoría visual ni equivalencia de Aleph.
No se invocaron watch, resident/open, screenshot, refresh, install ni actualización.

qa/verify_officecli_isolated.py exige sandbox-exec, HOME/TMP propios y entorno mínimo.
Perfil deniega red, escrituras fuera del run, contenido bajo Users/Applications salvo
ejecutable/run permitido, y señales a otros procesos. Permite metadatos de ancestros
Users para resolver el ejecutable, no contenido privado. Guardas sintéticas verifican
lectura/escritura de sibling denegadas y bind de socket denegado (errno1).
Temporales .officecli-validation.*/ ignorados, no son recursos distribuibles.
Kit backend y OpenWork fijan OFFICECLI_SKIP_UPDATE=1 y OFFICECLI_NO_AUTO_INSTALL=1.

## Fuentes/build y licencia

Identidad con un release oficial demuestra procedencia de distribución, no reconstrucción
independiente desde fuentes. Recetas de ese tag conservadas en upstream-evidence/
v1.0.145-officecli.csproj y v1.0.145-build.yml (hash original en JSON).
.NET10 self-contained single-file/trimmed; CI .NET10.0.x/macOS-latest y firma timestamp.
No hay .NET instalado localmente; no se instaló ni reconstruyó: no es necesario para
la identidad exacta del asset y consumiría margen para el build posterior.
No se afirma bit-reproducibilidad, attestation source-to-binary ni autoría criptográfica.

Apache-2.0 permite redistribución bajo sus condiciones. LICENSE, NOTICE y
THIRD-PARTY-NOTICES.txt son idénticos al tag1.0.145 y se conservan íntegros;
spec incluye los avisos. No se cambió SUL/licencia Aleph ni se inventó titular.
Firma del nuevo paquete y equivalencia de toda Aleph siguen para su fase autorizada.
