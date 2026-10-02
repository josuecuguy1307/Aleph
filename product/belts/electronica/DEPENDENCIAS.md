# Electrónica: dependencias externas
Opcionales para Aleph global, requeridas para las tools correspondientes:
- ac_sweep: ngspice, localizado por NGSPICE_BIN o ngspice en PATH.
- build_filter_schematic: intérprete con mcp_kicad_sch_api; KICAD_SCH_API_PY
  selecciona un ejecutable Python explícito. Por defecto usa sys.executable.
- run_erc: KICAD_CLI_BIN o kicad-cli en PATH.

El manifest no sobrescribe esas variables con rutas de una máquina particular.
No se incluye ni instala KiCad automáticamente. Proveer un entorno independiente compatible,
verificar import mcp_kicad_sch_api y kicad-cli --version antes de habilitar estas herramientas.
Una dependencia ausente produce error de la tool; no omitir ni fabricar el resultado.
El preflight verifica el mismo KICAD_SCH_API_PY/default.
