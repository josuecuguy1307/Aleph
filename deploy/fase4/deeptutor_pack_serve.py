"""Entrada congelable del backend de Aleph Educación.

Es un ejecutable independiente, no un segundo sidecar de Aleph: el launcher del
pack lo mantiene dentro del mismo grupo de proceso F4 que Next y lo termina con
él. Separarlo permite distribuir el runtime Python del tutor sin depender del
Python del usuario ni de un virtualenv dentro de la .app.
"""
from deeptutor.api.run_server import main


if __name__ == "__main__":
    main()
