"""Residuo de la capa de canales de mensajería — ver ../../EXTIRPACIONES.md.

Aleph amputó los 16 adaptadores de IM y toda su maquinaria (bus, manager,
runtime, registry, pairing, config): son superficie de producto independiente,
no oficio financiero, y Aleph es local y mono-usuario.

Lo único que sobrevive de este paquete es :mod:`src.channels.utils`, y no por
descuido: ``src/security/network.py`` y ``src/security/workspace_policy.py``
re-exportan de ahí la validación de URL (anti-SSRF) y la contención de rutas.
Moverlo sería refactor, y la importación no refactoriza (third_party/README.md,
Ley 5). Queda anotado como deuda en ``IMPORT.md``.

Este ``__init__`` no re-exporta nada a propósito: los nombres que exportaba
(``BaseChannel``, ``ChannelManager``, ``MessageBus``, ``InboundMessage``,
``OutboundMessage``) ya no existen en el árbol.
"""

__all__: list[str] = []
