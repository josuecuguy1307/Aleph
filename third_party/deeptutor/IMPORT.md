# DeepTutor — origen de esta importación

| campo | valor |
|---|---|
| Repo origen | https://github.com/HKUDS/DeepTutor |
| Commit importado | `456f9c24226e008f1ff07a7e3455d7b4d39f6221` (v1.5.11) |
| Árbol Git upstream | `4d6dd856548d1e9918f2c374febfde1824f04003` |
| SHA-256 del manifiesto bruto | `2a5c7c42213ff09c3e99b7de3ca4bb756c3766b61f338b04b4f671525ff84825` |
| Licencia del repositorio | Apache-2.0 (`LICENSE` y `pyproject.toml`) |
| Fecha de importación | 2026-08-09 |
| Estudio previo | `~/Desktop/FASE6-EDUCACION-ESTUDIO.md` |
| Frontera | repo entero, sin `.git`, sin historial ni dependencias instaladas |

## Copia en bruto — vara de entrada

Se copiaron los **6.257 archivos rastreados** del clon de estudio. El SHA-256 es el hash
del manifiesto ordenado `sha256 archivo` de ese árbol sin `.git`. Antes de cualquier
corte, `diff -qr --exclude .git` entre
`~/Desktop/oss-estudio/deeptutor/` y esta carpeta no produjo diferencias. El clon fuente
permanece limpio y es el testigo intacto de `456f9c2`.

La unidad es el repositorio entero: backend Python, frontend, CLI, tests y documentos. No
se tomaron fragmentos. Las operaciones posteriores son amputaciones de Ley 0/2.bis/2.ter y
están inventariadas en [`EXTIRPACIONES.md`](EXTIRPACIONES.md).

## Licencia y frontera de dependencias

El código del repo es Apache-2.0, pero **PyMuPDF no entra**. Era una dependencia core
AGPL/comercial; se elimina junto con `pymupdf4llm`. El reemplazo elegido es `pypdfium2`,
con licencia Apache-2.0 / BSD-3-Clause y licencias de PDFium que deben viajar con toda
wheel binaria. La decisión, capacidad equivalente y vara viven en `EXTIRPACIONES.md`.

No se instala ni configura un proveedor de modelo propio. El único perfil permitido es
`binding: "custom"` hacia el borde OpenAI-compatible de Aleph; su endpoint, credencial y
pack no se modifican desde esta importación. La forma exacta de catálogo y el testigo del
recorrido tutor → artefacto están en `../FASE6-EDUCACION.md` y
`reports/gate4-educacion/tutoria-testigo.json`.
