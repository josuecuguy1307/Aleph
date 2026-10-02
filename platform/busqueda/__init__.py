"""busqueda — el índice de búsqueda de la casa. [Convergencia · Superficie 5]

Una consulta, tres grupos (hilos · mensajes · artefactos) sobre FTS5, con el dueño y el
espacio como TOKENS del MATCH — sin dueño la consulta no se construye. Importado
top-level como `busqueda.*`, igual que `artifacts.*` y `gates.*` (`platform/` va en
sys.path, cableado por `product/backend/app/main.py`).

Lo que NO indexa —los chunks del matter de Legal, el knowledge de Educación, los stores
internos de los stacks— está escrito con su porqué en `indice.py`. Cada workspace
conserva su búsqueda: ésta se suma encima.
"""
