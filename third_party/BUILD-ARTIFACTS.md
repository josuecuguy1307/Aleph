# Artefactos de build no incluidos

Los directorios `deeptutor/bin`, `openscience/bin`, `vibetrading/bin` y `openwork/bin`
se generan durante el flujo de empaquetado definido en `deploy/fase4/`. En el árbol de
origen eran enlaces absolutos hacia `/Applications/Aleph.app`; fueron retirados de esta
copia para que el repositorio no dependa de una instalación local ni de su bundle.

La especificación `deploy/fase4/aleph_sidecar.spec` conserva las comprobaciones y los
pasos necesarios para producirlos antes de construir un paquete nuevo.
