# gws — distribución y skills selectivas

- Origen verificado: `https://github.com/googleworkspace/cli`
- Commit: `a3768d0e82ad83cca2da97724e46bea4ff0e6dbd`
- Release empaquetado: `v0.22.5`, macOS arm64
- Licencia: Apache-2.0 (`LICENSE` conservada)
- SHA-256 del archivo publicado y verificado:
  `1d2a9ffd5bc9b2c2c4b48630daf082fad13d9e57d741988a2c248eed562f7dac`

Sólo entran las cuatro skills autorizadas: `gws-gmail`, `gws-calendar`,
`gws-docs` y `gws-sheets`. La referencia upstream a `gws-shared` no se
importa: Aleph sustituye sus instrucciones de autenticación por el broker
per-user documentado en `platform/belts/oficina/README.md`; no se permite
`gws auth setup`, `gws auth login` ni su almacén local de credenciales.
