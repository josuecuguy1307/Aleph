# Tutor STEM portable
El manifest .mcp.json se consume a través del assembler de Aleph, que garantiza y expande
PUPPET_REPO al root de recursos. El CLI assembler resuelve belt_path relativo a config_path.
Preparar product/tutor-stem/.venv con las dependencias declaradas del tutor;
mcp-sympy y Python deben existir allí. No se hizo instalación durante saneamiento.
Un cliente MCP externo sin expansión de variables debe generar su configuración con paths
resueltos explícitamente: no entregar estos placeholders directamente a subprocess.
Chart continúa usando npx y requiere red; no se ejecutó durante validaciones.
