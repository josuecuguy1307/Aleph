from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.phase1 import centro_modelos as cm

_CLI_SESIONES_REAL = cm.cli_sesiones


def test_cli_snapshot_keeps_access_separate_from_auth(monkeypatch, tmp_path):
    from cli_brain import detect, lifecycle
    monkeypatch.setattr(cm, "_cli_sesiones_path", lambda: tmp_path / "cli-sessions.json")
    monkeypatch.setattr(detect, "detect_all", lambda **kwargs: {
        "claude_cli": {"provider": "claude_cli", "state": "access_denied",
                       "installed": True, "auth_state": "authenticated",
                       "access_state": "denied", "last_test_state": "failed",
                       "last_error_kind": "access_denied", "detail": "provider denied"},
    })
    monkeypatch.setattr(lifecycle, "service_status", lambda: {"state": "ready"})
    result = _CLI_SESIONES_REAL(fresco=True)
    claude = result["providers"]["claude_cli"]
    assert claude["auth_state"] == "authenticated"
    assert claude["access_state"] == "denied"
    assert claude["last_test_state"] == "failed"


def _base():
    return {
        "filas": [
            {
                "slug": "incluido.cognicion", "familia": cm.INCLUIDO,
                "ref": "cognicion", "label": "Incluido", "estado": cm.ROTO,
                "causa": "error_upstream", "frontier": True, "local": False,
            },
            {
                "slug": "cli.claude_cli", "familia": cm.CLI,
                "ref": "claude_cli", "label": "Claude Code",
                "estado": cm.DETECTADO, "causa": None, "frontier": True, "local": False,
            },
            {
                "slug": "api.groq", "familia": cm.API,
                "ref": "groq", "label": "Groq", "estado": cm.NO_CONFIGURADO,
                "causa": None, "frontier": False, "local": False, "hay_llave": False,
            },
        ],
        "categorias": [
            {"id": c["id"], "es": c["es"], "en": c["en"]}
            for c in cm.CATEGORIAS
        ],
        "maquina": {"disco_libre_gb": 20, "ram_libre_gb": 12},
    }


@pytest.fixture()
def v2_env(monkeypatch, tmp_path):
    monkeypatch.setattr(cm, "modelos_dir", lambda: tmp_path)
    monkeypatch.setattr(cm, "filas", lambda owner=None, get_conn=None: _base())
    monkeypatch.setattr(cm, "cli_sesiones", lambda fresco=False: {
        "providers": {
            "claude_cli": {
                "provider": "claude_cli", "state": "ready",
                "detail": "sesión activa",
            },
        },
        "service": {"state": "ready", "detail": "listener vivo"},
        "actual": True, "persistida": False, "ts": 1234.0,
    })
    calls = []

    def catalogo(categoria, formato=None, limite=2):
        calls.append(categoria)
        return {
            "red": True, "categoria": categoria, "modelos": [{
                "id": f"acme/{categoria}-7B-GGUF", "org": "acme",
                "nombre": f"{categoria}-7B-GGUF", "formato": "gguf",
                "archivo": "model-q4.gguf", "archivos": ["model-q4.gguf"],
                "peso_gb": 4.0, "tier": "medio", "categoria": categoria,
                "veredicto": {
                    "veredicto": "comodo", "es": "Entra cómodo",
                    "en": "Fits comfortably", "ram_pedida_gb": 5.3,
                },
                "url": f"https://huggingface.co/acme/{categoria}-7B-GGUF",
            }],
        }

    monkeypatch.setattr(cm, "catalogo_hf", catalogo)
    return tmp_path, calls


def test_v2_es_un_lote_y_cada_hf_trae_veredicto(v2_env):
    _, calls = v2_env
    out = cm.filas_v2(limite_hf=1)
    hf = [f for f in out["filas"] if f.get("hf")]

    assert out["contrato"]["lote"] is True
    assert out["contrato"]["requests_listado"] == 1
    assert len(calls) == len(cm.CATEGORIAS)
    assert len(hf) == len(cm.CATEGORIAS)
    assert all(f["veredicto"]["veredicto"] == "comodo" for f in hf)
    assert out["contrato"]["veredictos_en_fila"] is True
    assert out["contrato"]["requests_sidecar"] == 1
    assert all(f["familia"] == cm.LOCAL and f["destino"] == "descarga_local" for f in hf)
    assert all(f["inference_api"] is False for f in hf)
    assert out["hf"]["inference_api"] is False


def test_calibracion_peso_o_veredicto_desconocido_no_pasa_en_silencio(v2_env, monkeypatch):
    def roto(categoria, formato=None, limite=2):
        return {
            "red": True, "categoria": categoria,
            "modelos": [{
                "id": f"acme/{categoria}", "org": "acme", "nombre": categoria,
                "formato": "gguf", "archivo": "x.gguf", "archivos": ["x.gguf"],
                "peso_gb": None, "tier": "chico", "categoria": categoria,
                "veredicto": {
                    "veredicto": "desconocido",
                    "es": "No sé cuánto pesa",
                    "en": "Unknown size",
                },
            }],
        }

    monkeypatch.setattr(cm, "catalogo_hf", roto)
    out = cm.filas_v2(limite_hf=1)
    assert out["contrato"]["veredictos_en_fila"] is False
    assert out["contrato"]["candidatos_rechazados"] == len(cm.CATEGORIAS)
    assert not any(f.get("hf") for f in out["filas"])
    assert out["hf"]["red"] is False
    assert all("peso comparable" in r["detalle"] for r in out["hf"]["rechazados"])


def test_lote_recalcula_veredicto_faltante_si_el_peso_si_es_real(v2_env, monkeypatch):
    def reparable(categoria, formato=None, limite=2):
        return {
            "red": True, "categoria": categoria,
            "modelos": [{
                "id": f"acme/{categoria}", "org": "acme", "nombre": categoria,
                "formato": "gguf", "archivo": "x.gguf", "archivos": ["x.gguf"],
                "peso_gb": 1.0, "tier": "chico", "categoria": categoria,
                "veredicto": {"veredicto": "desconocido"},
            }],
        }

    monkeypatch.setattr(cm, "catalogo_hf", reparable)
    out = cm.filas_v2(limite_hf=1)
    hf = [f for f in out["filas"] if f.get("hf")]
    assert len(hf) == len(cm.CATEGORIAS)
    assert all(f["veredicto"]["veredicto"] == "comodo" for f in hf)
    assert out["contrato"]["veredictos_en_fila"] is True


def test_veredicto_ram_pone_el_faltante_primero_en_la_fila():
    out = cm.veredicto(8.0, {
        "disco_libre_gb": 100,
        "ram_libre_gb": 4,
        "ram_total_gb": 8,
    })
    assert out["veredicto"] == "no_entra"
    assert out["razon"] == "ram"
    assert out["es"].startswith(f"No entra: te faltan {out['falta_gb']} GB de RAM")


def test_modelo_fuera_del_plan_conserva_causa_elegir_otro(monkeypatch):
    fila = next(h for h in cm.HOSTEADOS if h["slug"] == "api.openai")
    monkeypatch.setattr(cm.MV, "estado", lambda *args, **kwargs: {
        "estado": cm.ROTO,
        "causa": cm.MV.MODELO_NO_DISPONIBLE,
        "ts": 123,
    })
    out = cm._estado_hosteado(fila, owner=None, get_conn=None)
    assert out["estado"] == cm.ROTO
    assert out["causa"] == cm.MV.MODELO_NO_DISPONIBLE
    assert out["causa"] != cm.MV.PLAN_INSUFICIENTE


def test_selector_solo_conectados_mas_default_y_guia_interseca_frontier(v2_env):
    path, _ = v2_env
    # Default caído plantado: debe seguir visible para que el guard lo pueda interceptar.
    (path / "preferencias-v2.json").write_text(json.dumps({
        "version": 2, "default": "incluido.cognicion",
        "contextos": {}, "conectados": [],
    }), "utf-8")

    normal = cm.selector_modelos()
    assert {m["slug"] for m in normal["modelos"]} == {
        "incluido.cognicion", "cli.claude_cli",
    }
    assert normal["default"] == "incluido.cognicion"
    assert normal["regla"] == "conectados+default"

    guia = cm.selector_modelos(contexto="guia")
    assert {m["slug"] for m in guia["modelos"]} == {
        "incluido.cognicion", "cli.claude_cli",
    }
    assert all(m["frontier"] for m in guia["modelos"])
    assert guia["regla"].endswith("∩ frontier")


def test_selector_declara_capacidades_tecnicas_de_rutas_comprobadas(v2_env):
    out = cm.selector_modelos(todos=True)
    por_slug = {m["slug"]: m for m in out["modelos"]}
    assert "tool_calling" in por_slug["incluido.cognicion"]["model_use_capabilities"]
    assert "tool_calling" in por_slug["cli.claude_cli"]["model_use_capabilities"]
    assert "code" in por_slug["cli.claude_cli"]["model_use_capabilities"]


def test_toda_via_hosteada_declara_su_piso_tecnico():
    """Sin piso, una vía de API sin catálogo queda conectada y sin matriz: inadmisible."""
    sin = [k for k, v in cm._PICKER_HOSTEADO.items() if "model_use_capabilities" not in v]
    assert sin == [], f"vías sin matriz declarada: {sin}"
    for slug, fila in cm._PICKER_HOSTEADO.items():
        caps = set(fila["model_use_capabilities"])
        assert {"text", "streaming"} <= caps, slug
        # El piso NO promete lo que varía por modelo: eso lo concede el catálogo vivo.
        if slug.startswith("api."):
            assert caps == {"text", "streaming"}, slug


def test_la_matriz_de_un_local_sale_de_la_prueba_que_se_le_corrio():
    # `razonamiento`, `codigo` y `rapido` son tres rasgos con la MISMA prueba: `texto`.
    for categoria in ("razonamiento", "codigo", "rapido"):
        assert cm.matriz_de_local(categoria) == ["streaming", "text"], categoria
    assert cm.matriz_de_local("vision") == ["streaming", "text", "vision"]
    # Un modelo de embeddings NO hace chat: admitirlo para una charla sería inventar.
    assert cm.matriz_de_local("embeddings") == ["embeddings"]
    # Sin categoría no se sabe, y «no se sabe» es ausente, jamás una lista vacía.
    assert cm.matriz_de_local(None) is None
    assert cm.matriz_de_local("no-existe") is None


def test_default_y_eleccion_contextual_solo_aceptan_conectados(v2_env):
    base = cm._anotar_conectados(_base(), cm.cli_sesiones())
    filas = base["filas"]

    pref = cm.guardar_preferencias({
        "default": "cli.claude_cli",
        "contexto": "sala",
        "seleccion": "cli.claude_cli",
    }, filas)
    assert pref["default"] == "cli.claude_cli"
    assert pref["contextos"]["sala"] == "cli.claude_cli"

    with pytest.raises(cm.HTTPException) as exc:
        cm.guardar_preferencias({"default": "api.groq"}, filas)
    assert exc.value.status_code == 409

    with pytest.raises(cm.HTTPException) as exc:
        cm.guardar_preferencias({
            "contexto": "guia", "seleccion": "api.groq",
        }, filas)
    assert exc.value.status_code == 409


def test_default_es_uno_aun_sin_conectados_y_no_pisa_el_caido(v2_env, monkeypatch):
    path, _ = v2_env
    monkeypatch.setattr(cm, "cli_sesiones", lambda fresco=False: {
        "providers": {
            "claude_cli": {
                "provider": "claude_cli", "state": "no_auth",
                "detail": "la sesión venció",
            },
        },
        "service": {"state": "ready", "detail": "listener vivo"},
        "actual": True, "persistida": False, "ts": 1234.0,
    })
    base = cm._anotar_conectados(_base(), cm.cli_sesiones())
    assert not any(f["conectado"] for f in base["filas"])

    # [convergencia · s3 · fase 1] LAS PREFERENCIAS SON DE ALGUIEN. Este test leía y
    # escribía el archivo GLOBAL: la elección de una cuenta era la de la otra en la misma
    # Mac. Ahora la clave es (dueño, recurso) y el dueño va explícito.
    DUENIO = "usuario-de-prueba"
    pref = cm._preferencias_normalizadas(base["filas"], owner=DUENIO)
    assert pref["default"] == "incluido.cognicion"
    assert pref["default_caido"] is True
    assert pref["default_estado"]["popup"] == "al_usarlo"
    assert [c["accion"] for c in pref["default_estado"]["caminos"]] == [
        "reconectar", "usar_otro_conectado",
    ]
    assert sum(f["slug"] == pref["default"] for f in base["filas"]) == 1

    # Una lectura posterior conserva el mismo Default caído; no lo reemplaza por orden.
    otra = cm._preferencias_normalizadas(list(reversed(base["filas"])), owner=DUENIO)
    assert otra["default"] == "incluido.cognicion"
    guardado = json.loads((path / "preferencias" / f"{DUENIO}.json").read_text("utf-8"))
    assert guardado["default"] == "incluido.cognicion"

    # LA GARANTÍA NUEVA: sin dueño se LEE pero no se ESCRIBE. Antes, una lectura anónima
    # persistía el default derivado en el archivo de todos.
    anon = cm._preferencias_normalizadas(base["filas"])
    assert anon["default"] == "incluido.cognicion"          # la lectura sigue sirviendo
    assert not (path / "preferencias-v2.json").exists(), \
        "una lectura sin dueño escribió en el archivo global"

    # Y un SEGUNDO dueño no hereda la elección del primero.
    otro = cm._preferencias_normalizadas(base["filas"], owner="otra-cuenta")
    assert (path / "preferencias" / "otra-cuenta.json").exists()
    assert (path / "preferencias" / f"{DUENIO}.json").read_text("utf-8") is not None


def test_sesion_cli_se_revalida_y_snapshot_stale_jamas_da_verde(
        v2_env, monkeypatch):
    path, _ = v2_env
    monkeypatch.syspath_prepend(
        str(Path(cm.__file__).resolve().parents[4] / "platform" / "assembler"))
    from cli_brain import detect, lifecycle

    llamadas = []

    def ready(*, ttl=None, public=False):
        llamadas.append({"ttl": ttl, "public": public})
        return {
            "claude_cli": {
                "provider": "claude_cli", "state": "ready", "installed": True,
                "detail": "sesión activa", "binary": "/secreto/claude",
                "token": "no-debe-salir",
            },
            "codex_cli": {
                "provider": "codex_cli", "state": "not_installed",
                "installed": False, "detail": "no instalado",
            },
        }

    monkeypatch.setattr(detect, "detect_all", ready)
    monkeypatch.setattr(lifecycle, "service_status", lambda: {
        "state": "ready", "mode": "managed", "detail": "listener vivo",
    })
    viva = _CLI_SESIONES_REAL(fresco=True)
    assert llamadas == [{"ttl": 0, "public": True}]
    assert viva["actual"] is True
    assert viva["providers"]["claude_cli"]["state"] == "ready"
    assert "binary" not in viva["providers"]["claude_cli"]
    assert "token" not in viva["providers"]["claude_cli"]
    assert (path / "sesiones-cli-v2.json").exists()

    def cae(*, ttl=None, public=False):
        return {
            "claude_cli": {
                "provider": "claude_cli", "state": "no_auth",
                "installed": True, "detail": "la sesión venció",
            },
            "codex_cli": {
                "provider": "codex_cli", "state": "not_installed",
                "installed": False, "detail": "no instalado",
            },
        }

    monkeypatch.setattr(detect, "detect_all", cae)
    caida = _CLI_SESIONES_REAL(fresco=True)
    assert caida["caidas"][0]["provider"] == "claude_cli"
    assert caida["caidas"][0]["causa"] == cm.MV.SIN_SESION

    monkeypatch.setattr(detect, "detect_all", lambda **kwargs: (_ for _ in ()).throw(
        RuntimeError("detector fuera")))
    stale = _CLI_SESIONES_REAL(fresco=True)
    assert stale["actual"] is False and stale["persistida"] is True
    base = cm._anotar_conectados(_base(), stale)
    cli = next(f for f in base["filas"] if f["slug"] == "cli.claude_cli")
    assert cli["conectado"] is False
    assert cli["estado"] != cm.PROBADO


def test_router_documenta_endpoints_v2_batch_selector_prefs_y_cli():
    router = cm.build_modelos_router()
    rutas = {
        (route.path, method)
        for route in router.routes
        for method in (route.methods or set())
    }
    assert ("/v1/modelos/v2", "GET") in rutas
    assert ("/v1/modelos/catalogo/lote", "GET") in rutas
    assert ("/v1/modelos/selector", "GET") in rutas
    assert ("/v1/modelos/preferencias", "GET") in rutas
    assert ("/v1/modelos/preferencias", "PUT") in rutas
    assert ("/v1/modelos/cli/sesiones", "GET") in rutas


def test_cerrar_sse_limpia_part_y_carpeta_incompleta(v2_env, monkeypatch):
    path, _ = v2_env
    job = cm.Descarga(
        "acme-demo", "acme/demo", "modelo.gguf", "gguf",
        "codigo", 1.0, "chico",
    )

    def parcial(j):
        carpeta = path / j.slug
        carpeta.mkdir()
        part = carpeta / "modelo.gguf.part"
        part.write_bytes(b"incompleto")
        j.carpeta = carpeta
        j.parcial = part
        j.destino = carpeta / "modelo.gguf"
        j.estado = "descargando"
        yield {"tipo": "progreso"}

    monkeypatch.setattr(cm, "_descargar", parcial)
    gen = cm.descargar(job)
    assert next(gen)["tipo"] == "progreso"
    gen.close()

    assert job.estado == "cancelado"
    assert job.causa == cm.DESCARGA_CANCELADA
    assert not (path / job.slug).exists()


def test_archivo_ya_bajado_igual_instala_prueba_y_termina_verde(
        v2_env, monkeypatch):
    path, _ = v2_env
    carpeta = path / "acme-demo"
    carpeta.mkdir()
    (carpeta / "modelo.gguf").write_bytes(b"modelo-completo")
    job = cm.Descarga(
        "acme-demo", "acme/demo", "modelo.gguf", "gguf",
        "codigo", 1.0, "chico",
    )
    monkeypatch.setattr(cm, "maquina", lambda: {
        "disco_libre_gb": 20,
        "ram_libre_gb": 12,
        "ram_total_gb": 16,
    })
    monkeypatch.setattr(cm, "runtime_de", lambda formato, maq: {
        "vivo": True, "detalle": "listo", "mano": {},
    })
    monkeypatch.setattr(cm, "instalar", lambda j: {
        "estado": cm.DETECTADO, "causa": None, "ollama_tag": "aleph-demo",
    })
    monkeypatch.setattr(cm, "probar_local", lambda slug, tag=None, categoria=None: {
        "slug": slug, "estado": cm.PROBADO, "causa": None,
        "detalle": "corrió", "evidencia": {"respuesta": "4"}, "ts": 42,
    })
    monkeypatch.setattr(cm, "_anotar", lambda *args, **kwargs: None)

    eventos = list(cm.descargar(job))
    tipos = [e["tipo"] for e in eventos]
    assert "instalando" in tipos and "probando" in tipos and "prueba" in tipos
    assert eventos[-1]["tipo"] == "fin"
    assert eventos[-1]["estado"] == cm.PROBADO
    assert job.descarga_completa is True


# ══════════════════════════════════════════════════════════════════════════════════
# [F7 · obra 3] LA FILA LLEVA SU EVIDENCIA Y SU FECHA
#
# Medido el 2026-08-06: las 8 filas de la vía API llegaban al front SIN campo `prueba` —
# o sea sin [?] posible y sin fecha, y «🟢 probado» a secas. El motor ya medía y ya
# guardaba el porqué; la fila lo tiraba.
# ══════════════════════════════════════════════════════════════════════════════════
def test_la_fila_api_lleva_la_evidencia_del_motor_con_su_fecha(monkeypatch):
    from app.phase1 import motor_verdad as MV

    medido = MV._resultado(MV.KEY, "openrouter", MV.PROBADO, ts=1700.0, evidencia={
        "detail": "openrouter generó con tu llave (openai/gpt-4o, primer pedazo en 812 ms)",
        "prueba": "generacion", "discriminante": False, "latencia_ms": 812,
    })
    monkeypatch.setattr(MV, "estado",
                        lambda tipo, ref, **kw: ({**medido, "cacheado": True}
                                                 if ref == "openrouter"
                                                 else {"estado": MV.DETECTADO, "ts": 9999.0,
                                                       "cacheado": False,
                                                       "evidencia": {"nunca_probado": True}}))

    porslug = {f["slug"]: f for f in cm.filas(owner="u1", get_conn=None)["filas"]}
    p = porslug["api.openrouter"]["prueba"]
    assert p is not None, "la fila API tiene que llevar su prueba"
    assert p["ts"] == 1700.0                       # ← la FECHA, que es lo que envejece
    assert "generó con tu llave" in p["detalle"]   # ← el DETALLE, que es lo que muestra el [?]
    assert p["evidencia"]["prueba"] == "generacion"

    # ⚠️ Y LO QUE NUNCA SE MIDIÓ NO TIENE PRUEBA. `MV.estado` devuelve un placeholder con
    # `ts` FRESCO cuando nunca se probó: emitirlo sería un [?] vacío y una fecha que hace
    # pasar por recién medido algo que no se midió — y que por eso nunca envejecería.
    assert porslug["api.openai"]["prueba"] is None


# ══════════════════════════════════════════════════════════════════════════════════
# [F8 · obra 2] LA ELECCIÓN DE MODELO POR PROVEEDOR — que SOBREVIVA es la mitad cara
# ══════════════════════════════════════════════════════════════════════════════════
def _catalogo_falso(monkeypatch, ids):
    """El catálogo vivo del proveedor, sin red. `fuente: red` para que el veredicto de
    `verificar_vigente` sea real: sobre un catálogo vacío esa función se calla a propósito,
    y entonces el test no estaría midiendo la validación sino su ausencia."""
    monkeypatch.setattr(cm._disc, "descubrir", lambda ref, key=None, **kw: {
        "provider_id": ref, "fuente": "red", "descubierto_en": "2026-08-07T00:00:00",
        "rancio": False,
        "modelos": [{"provider_id": ref, "model_id": i, "label": i,
                     "context": 131072, "capacidades": ["texto", "tools"], "free": False}
                    for i in ids],
    })


def test_eleccion_de_modelo_persiste_y_sobrevive_a_la_normalizacion(v2_env, monkeypatch):
    """★ EL TRAP DE ESTA OBRA: `_preferencias_normalizadas` REARMA el dict que escribe a
    disco. Una clave que no esté en ese rearmado se pierde en la PRÓXIMA PINTADA — o sea que
    el usuario elige, ve su modelo, y al volver a abrir la pantalla la elección no está."""
    _catalogo_falso(monkeypatch, ["llama-3.3-70b", "gpt-oss-120b"])
    filas = cm._anotar_conectados(_base(), cm.cli_sesiones())["filas"]

    pref = cm.guardar_preferencias({"slug": "api.groq", "modelo": "llama-3.3-70b"}, filas)
    assert pref["modelos"]["api.groq"] == "llama-3.3-70b"

    # …y sigue ahí después de que otra pantalla normalice (que es lo que pasa en cada pintada)
    de_nuevo = cm._preferencias_normalizadas(filas)
    assert de_nuevo["modelos"]["api.groq"] == "llama-3.3-70b"
    en_disco = json.loads((cm.modelos_dir() / "preferencias-v2.json").read_text("utf-8"))
    assert en_disco["modelos"]["api.groq"] == "llama-3.3-70b"

    # ★ Y UNA LISTA PARCIAL NO LA BORRA. `contextos` sí se filtra contra las filas que le
    # pasen; la elección de modelo NO, justamente para que una pantalla que normaliza con
    # media lista no le borre al usuario una decisión que tomó una vez.
    parcial = cm._preferencias_normalizadas([f for f in filas if f["familia"] != cm.API])
    assert parcial["modelos"]["api.groq"] == "llama-3.3-70b"


def test_eleccion_de_modelo_se_puede_devolver_a_aleph(v2_env, monkeypatch):
    """Elegir tiene que ser reversible. Sin esta salida, quien probó un modelo una vez queda
    casado con él: la ley dice que Aleph elige un default sensato, y volver a ese estado es
    parte de la ley, no un extra."""
    _catalogo_falso(monkeypatch, ["llama-3.3-70b"])
    filas = cm._anotar_conectados(_base(), cm.cli_sesiones())["filas"]
    cm.guardar_preferencias({"slug": "api.groq", "modelo": "llama-3.3-70b"}, filas)
    pref = cm.guardar_preferencias({"slug": "api.groq", "modelo": ""}, filas)
    assert "api.groq" not in (pref["modelos"] or {})


def test_eleccion_de_modelo_rechaza_lo_que_no_existe_y_lo_que_no_se_elige(v2_env, monkeypatch):
    _catalogo_falso(monkeypatch, ["llama-3.3-70b"])
    filas = cm._anotar_conectados(_base(), cm.cli_sesiones())["filas"]

    # un id que NO está en el catálogo vivo del proveedor
    with pytest.raises(cm.HTTPException) as exc:
        cm.guardar_preferencias({"slug": "api.groq", "modelo": "inventado-9000"}, filas)
    assert exc.value.status_code == 409

    # una vía que no es de API: un CLI usa el modelo de su suscripción y un local el que está
    # bajado. Ofrecer «elegí modelo» ahí sería un menú sobre algo que no se elige.
    with pytest.raises(cm.HTTPException) as exc:
        cm.guardar_preferencias({"slug": "cli.claude_cli", "modelo": "lo-que-sea"}, filas)
    assert exc.value.status_code == 409

    with pytest.raises(cm.HTTPException) as exc:
        cm.guardar_preferencias({"slug": "api.no_existe", "modelo": "x"}, filas)
    assert exc.value.status_code == 404


def test_sin_catalogo_no_hay_veredicto_al_guardar(v2_env, monkeypatch):
    """MISMA LEY QUE `verificar_vigente`: con la red caída no se puede afirmar «ese modelo no
    existe». Rechazar acá dejaría al usuario sin poder elegir justo cuando el proveedor no
    contesta — y por un diagnóstico que nadie midió."""
    monkeypatch.setattr(cm._disc, "descubrir", lambda ref, key=None, **kw: {
        "provider_id": ref, "fuente": "ninguna", "modelos": [], "causa": "sin_red",
    })
    filas = cm._anotar_conectados(_base(), cm.cli_sesiones())["filas"]
    pref = cm.guardar_preferencias({"slug": "api.groq", "modelo": "el-que-quiera"}, filas)
    assert pref["modelos"]["api.groq"] == "el-que-quiera"


# ══════════════════════════════════════════════════════════════════════════════════
# [F9] EXISTIR NO ES SERVIR — un modelo de voz no es un cerebro
# ══════════════════════════════════════════════════════════════════════════════════
#: El catálogo REAL de groq medido el 2026-08-07: 15 modelos, 4 que no sirven de cerebro.
#: Se reproducen los dos casos que existen de verdad (transcribe / habla), no inventados.
_NO_SERVIBLES = [
    {"provider_id": "groq", "model_id": "whisper-large-v3", "label": "Whisper",
     "context": 448, "capacidades": [], "free": False, "salidas": ["transcription"]},
    {"provider_id": "groq", "model_id": "canopylabs/orpheus-v1-english", "label": "Orpheus",
     "context": 8192, "capacidades": [], "free": False, "salidas": ["speech"]},
]


def _catalogo_mixto(monkeypatch):
    from app.phase1 import modelos_discovery as D
    monkeypatch.setattr(cm._disc, "descubrir", lambda ref, key=None, **kw: {
        "provider_id": ref, "fuente": "red", "descubierto_en": "2026-08-07T00:00:00",
        "rancio": False,
        "modelos": [
            {"provider_id": ref, "model_id": "llama-3.3-70b", "label": "Llama",
             "context": 131072, "capacidades": ["texto", "tools"], "free": False,
             "salidas": ["text"]},
        ] + _NO_SERVIBLES,
    })
    return D


def test_servible_es_una_regla_con_nombre_y_una_sola(monkeypatch):
    """La regla vivía como un `if` adentro de `elegir()`: sólo corría cuando elegía ALEPH.
    El guard que valida la elección del USUARIO no tenía cómo preguntarla sin copiarla."""
    from app.phase1 import modelos_discovery as D
    assert hasattr(D, "servible"), "la regla no tiene nombre: nadie más puede preguntarla"
    assert D.servible({"model_id": "llama-3.3-70b", "capacidades": ["texto", "tools"]})
    for m in _NO_SERVIBLES:
        assert not D.servible(m), f"{m['model_id']} no genera texto y sale servible"
    assert not D.servible({"model_id": "x-embed-3", "capacidades": ["texto"]})
    assert not D.servible({"model_id": "router-1", "capacidades": ["texto", "router"]})


def test_el_preferido_tambien_tiene_que_SERVIR(monkeypatch):
    """★ EL BUG MEDIDO: `elegir(preferido="canopylabs/orpheus-arabic-saudi")` devolvía ese
    id — un modelo de VOZ coronado cerebro del agente. La rama del preferido miraba sólo si
    existía en el catálogo y se disparaba ANTES del filtro."""
    from app.phase1 import modelos_discovery as D
    cat = {"provider_id": "groq", "fuente": "red", "modelos": [
        {"provider_id": "groq", "model_id": "llama-3.3-70b", "label": "L",
         "context": 131072, "capacidades": ["texto", "tools"], "free": False,
         "salidas": ["text"]}] + _NO_SERVIBLES}
    assert D.elegir(cat, preferido="whisper-large-v3") == "llama-3.3-70b", (
        "la preferencia del usuario se salta la única condición que hace usable un cerebro")
    # …y una preferencia que SÍ sirve sigue ganando: esto no le quita la decisión a nadie.
    assert D.elegir(cat, preferido="llama-3.3-70b") == "llama-3.3-70b"


def test_no_se_puede_elegir_un_modelo_que_no_sirve_de_cerebro(v2_env, monkeypatch):
    """★★ La puerta que F8 dejó a medias: `verificar_vigente` sólo pregunta «¿existe?».
    Elegir Whisper se aceptaba y el fallo aparecía a mitad del primer turno — el lugar más
    lejos posible de la decisión que lo causó."""
    _catalogo_mixto(monkeypatch)
    filas = cm._anotar_conectados(_base(), cm.cli_sesiones())["filas"]
    with pytest.raises(cm.HTTPException) as exc:
        cm.guardar_preferencias({"slug": "api.groq", "modelo": "whisper-large-v3"}, filas)
    assert exc.value.status_code == 409
    # ★ EL COPY SELLADO, no una frase genérica: dice QUÉ hace ese modelo.
    assert "Transcribe audio; no genera texto." in str(exc.value.detail), str(exc.value.detail)
    # el que sí sirve entra sin ruido
    pref = cm.guardar_preferencias({"slug": "api.groq", "modelo": "llama-3.3-70b"}, filas)
    assert pref["modelos"]["api.groq"] == "llama-3.3-70b"


def test_el_catalogo_del_picker_dice_cual_no_sirve(v2_env, monkeypatch):
    """El picker no puede ofrecer lo que el PUT va a rechazar. `servible` viaja por fila,
    con el MISMO criterio que decide el rechazo — no re-derivado en el cliente."""
    _catalogo_mixto(monkeypatch)
    filas = cm._anotar_conectados(_base(), cm.cli_sesiones())["filas"]
    pref = cm._preferencias_normalizadas(filas)
    cat = cm._disc.descubrir("groq")
    marcados = {m["model_id"]: cm._disc.servible(m) for m in cat["modelos"]}
    assert marcados == {"llama-3.3-70b": True, "whisper-large-v3": False,
                        "canopylabs/orpheus-v1-english": False}


def test_el_motivo_del_rechazo_sale_del_CATALOGO_y_no_miente(monkeypatch):
    """★★ COPY SELLADO POR PERSONA USUARIA (2026-08-07) tras barrer los catálogos REALES.

    La trampa que este test cierra: «no genera texto» es MENTIRA para 13 de los 30 casos de
    openrouter. `openai/gpt-audio` declara `out=["audio","text"]` y
    `google/gemini-3.1-flash-image` declara `out=["image","text"]` — los dos generan texto.
    Decirles lo contrario es mentirle a alguien que puede abrir el catálogo y verificar."""
    from app.phase1 import modelos_discovery as D
    def motivo(sal, caps=()):
        return D.motivo_no_servible({"model_id": "x", "capacidades": list(caps), "salidas": sal})

    # familia 1 · NO devuelve texto — y ahí sí se dice
    assert motivo(["transcription"]) == "Transcribe audio; no genera texto."
    assert motivo(["speech"]) == "Genera voz; no genera texto."

    # familia 2 · devuelve texto PERO NO SOLO — se le RECONOCE el texto
    assert motivo(["image", "text"]) == (
        "Devuelve imagen además de texto; el cerebro necesita solo texto.")
    assert motivo(["audio", "text"]) == (
        "Devuelve audio además de texto; el cerebro necesita solo texto.")
    for sal in (["image", "text"], ["audio", "text"]):
        assert "no genera texto" not in motivo(sal), (
            f"{sal} SÍ genera texto y el copy lo niega — desmentible abriendo el catálogo")

    # familia 3 · router: no es de modalidad, y su copy no habla de modalidades
    r = motivo(["image", "text"], caps=("texto", "router", "tools"))
    assert r == "Enruta a otros modelos: no se puede saber cuál respondió."
    assert "necesita solo texto" not in r, (
        "el router NO es un problema de modalidad: enruta bien y devuelve texto. Su copy "
        "habla de lo único que importa acá — que no se sabe qué modelo respondió")

    # lo que NO encaja en las tres: DERIVADO del catálogo, jamás mudo ni inventado
    assert motivo(["image", "audio", "text"]) == (
        "Devuelve imagen y audio además de texto; el cerebro necesita solo texto.")
    assert motivo(["hologram", "text"]) == (
        "Devuelve hologram además de texto; el cerebro necesita solo texto."), (
        "una modalidad que no conocemos se CITA tal como vino, no se renombra ni se calla")
    assert motivo([]) and "no declara" in motivo([]), "sin salidas declaradas, tampoco mudo"


def test_no_se_agregaron_causas_tipadas_por_esto(monkeypatch):
    """El rechazo va como DETALLE del 409, no como causa nueva (regla de persona usuaria): las causas
    tipadas son para lo que le pasa a algo CONECTADO; esto es validación de entrada."""
    from app.phase1 import motor_verdad as MV
    for inventada in ("modelo_sin_probar", "modelo_no_responde", "modelo_no_servible",
                      "modelo_no_es_cerebro"):
        assert inventada not in MV.CAUSAS, f"se coló una causa nueva: {inventada}"
    assert "modelo_no_elegido" in MV.CAUSAS, "la de F8 sigue en pie"


# ══════════════════════════════════════════════════════════════════════════════════
# [F9] «PRUEBA DE INFERENCIA» PRUEBA — y su resultado SOBREVIVE a la recarga
# ══════════════════════════════════════════════════════════════════════════════════
def test_el_verbo_prueba_CORRE_una_sonda_y_no_lee_un_flag(v2_env, monkeypatch):
    """★★ EL VERBO MENTÍA. `correr()` acepta sondas desde F4c y su ÚNICO llamador las
    omitía, así que «Prueba de inferencia» se resolvía con `fila.estado == "probado"`:
    leía el veredicto del PROVEEDOR y decía que había probado la inferencia.

    La prueba de que ahora MIDE: se planta una fila cuyo `estado` es `probado` —lo que antes
    bastaba para el ✓— y una sonda que FALLA. Si el verbo leyera el flag, saldría ok."""
    from app.phase1 import modelos_checklist as CK
    fila = {"familia": "api", "ref": "groq", "slug": "api.groq",
            "estado": "probado", "hay_llave": True}
    corridas = []

    def _sonda_que_falla():
        corridas.append(1)
        return False, "key_invalida", "el proveedor rechazó la credencial"

    evs = list(CK.correr(fila, sondas={"prueba": _sonda_que_falla}))
    assert corridas, "la sonda NI SIQUIERA se llamó: el verbo sigue leyendo un flag"

    # ★★ Y LO QUE DE VERDAD ESTABA ROTO ERA EL LLAMADOR, no este módulo: `correr()` acepta
    # sondas desde F4c y la ruta las OMITÍA. El guard es sobre el punto de llamada, porque
    # es lo único que distingue «el módulo sabe recibir sondas» de «alguien se las pasa».
    import re
    from pathlib import Path as _P
    fuente = (_P(cm.__file__)).read_text(encoding="utf-8")
    llamadas = re.findall(r"_CK\.correr\([^)]*\)", fuente)
    assert llamadas, "nadie llama al checklist"
    assert all("sondas=" in l for l in llamadas), (
        f"el checklist se corre SIN sondas: {llamadas} — el verbo volvería a leer un flag")
    prueba = [e for e in evs if e.get("verbo") == "prueba"
              and e["tipo"] == "requisito.resultado"][0]
    assert prueba["estado"] == "fallo" and prueba["causa"] == "key_invalida", prueba
    cierre = [e for e in evs if e["tipo"] == "fila.cerrada"][0]
    assert cierre["ok"] is False and cierre["verbo_culpable"] == "prueba"


def test_la_sonda_del_checklist_PERSISTE_su_veredicto(v2_env, monkeypatch):
    """★★ CONDICIÓN SELLADA POR PERSONA USUARIA: el resultado se persiste con evidencia y fecha.

    Sin esto el veredicto viviría sólo en el SSE: el checklist diría «probado» y la fila
    volvería a «sin probar» al recargar — el checklist afirmando algo que la pantalla
    desmiente treinta segundos después."""
    from app.phase1 import motor_verdad as MV
    llamadas = []

    def _probar_falso(tipo, ref, **kw):
        llamadas.append({"tipo": tipo, "ref": ref, **kw})
        return MV._resultado(MV.KEY, ref, MV.PROBADO,
                             evidencia={"detail": "la ruta de generación aceptó tu llave",
                                        "prueba": "auth_generacion"})
    monkeypatch.setattr(cm.MV, "probar", _probar_falso)
    fila = {"familia": "api", "ref": "groq", "slug": "api.groq", "hay_llave": True}
    sondas = cm._sondas_de(fila, "u1", lambda: None)
    assert "prueba" in sondas, "la vía API tiene que traer su sonda"
    ok, causa, detalle = sondas["prueba"]()
    assert ok and causa is None and "generación" in detalle

    # ★ va por `MV.probar` —que ESCRIBE en el store— y no por `veredicto_key` a secas.
    assert llamadas and llamadas[0]["tipo"] == MV.KEY and llamadas[0]["ref"] == "groq"
    assert llamadas[0]["force"] is True, "el checklist es un gesto explícito: mide de nuevo"
    assert llamadas[0]["motivo"] == "checklist_modelos", "queda por qué se midió"


def test_solo_la_via_API_trae_sonda(v2_env):
    """Las otras vías se resuelven con lo que la fila declara, medido río arriba. Re-medir
    todo desde cero es más lento y no más honesto."""
    for familia in ("cli", "local", "incluido"):
        assert cm._sondas_de({"familia": familia, "ref": "x"}, "u1", lambda: None) == {}
    assert cm._sondas_de({"familia": "api", "ref": "groq"}, None, lambda: None) == {}, (
        "sin sesión no hay vault que leer: no se inventa una sonda")


# ══════════════════════════════════════════════════════════════════════════════════
# ★★★ LEY SELLADA: LOS PROVEEDORES SON DATOS, NO CÓDIGO ★★★
#
# «Un proveedor nuevo —hoy o dentro de dos años— entra como una FILA declarada, jamás como
# un caso especial.» (persona usuaria, 2026-08-07)
#
# ESTA ES LA VARA QUE LA GUARDA. Mete un proveedor FICTICIO contra un stub local, SÓLO como
# filas de tablas, y exige que el sistema entero lo trate como a los otros ocho. Si algún
# día alguien mete un `if provider == …`, el ficticio se rompe PRIMERO — antes que ningún
# usuario.
# ══════════════════════════════════════════════════════════════════════════════════
import http.server
import threading as _threading

ZZ = "zz_proveedor_de_prueba"


class _StubProveedor(http.server.BaseHTTPRequestHandler):
    """Un proveedor que habla el dialecto OpenAI y nada más. Cero conocimiento de Aleph."""

    def log_message(self, *a):
        pass

    def _envia(self, code, obj):
        cuerpo = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def _con_llave(self):
        return (self.headers.get("Authorization") or "").startswith("Bearer zz-")

    def do_GET(self):
        if not self._con_llave():
            return self._envia(401, {"error": {"message": "missing api key"}})
        if self.path.endswith("/models"):
            return self._envia(200, {"data": [
                {"id": "zz-grande", "name": "ZZ Grande", "context_length": 128000,
                 "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
                 "supported_parameters": ["tools"], "pricing": {"prompt": "1", "completion": "1"}},
                {"id": "zz-chico", "name": "ZZ Chico", "context_length": 8000,
                 "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
                 "supported_parameters": [], "pricing": {"prompt": "0", "completion": "0"}},
                {"id": "zz-voz", "name": "ZZ Voz", "context_length": 4096,
                 "architecture": {"input_modalities": ["text"], "output_modalities": ["speech"]},
                 "supported_parameters": [], "pricing": {"prompt": "1", "completion": "1"}},
            ]})
        return self._envia(404, {"error": "nope"})

    def do_POST(self):
        ln = int(self.headers.get("Content-Length") or 0)
        cuerpo = json.loads(self.rfile.read(ln) or b"{}")
        if not self._con_llave():
            return self._envia(401, {"error": {"message": "missing api key"}})
        # la sonda: parámetro basura → 400 nombrándolo (como groq y openrouter, medido)
        if not isinstance(cuerpo.get("temperature", 0), (int, float)):
            return self._envia(400, {"error": {"message": "'temperature' : value must be a number"}})
        return self._envia(200, {"choices": [{"message": {"content": "ok"}}]})


@pytest.fixture()
def proveedor_ficticio(monkeypatch, tmp_path):
    """Da de alta ZZ **SÓLO como filas de tablas**. Ni una línea de código nueva.

    ⚠️ NO usa `v2_env` a propósito: esa fixture reemplaza `cm.filas` por una lista fija, y
    entonces la vara mediría el fixture en vez del sistema. Acá se deja la `filas()` REAL —
    que es justamente lo que tiene que descubrir al proveedor nuevo por sí sola."""
    from app.phase1 import motor_verdad as MV
    from app.phase1 import modelos_discovery as D
    monkeypatch.setattr(cm, "modelos_dir", lambda: tmp_path)
    monkeypatch.setattr(D, "_dir_cache", lambda: tmp_path)
    srv = http.server.HTTPServer(("127.0.0.1", 0), _StubProveedor)
    _threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}/v1"

    # ── LAS FILAS. Esto es TODO lo que debería hacer falta. ──────────────────────
    monkeypatch.setitem(MV._KEY_VALIDATORS, ZZ,
                        {"base": base, "header": "bearer",
                         "sonda": {"param": "temperature", "confirma_modelo": False}})
    monkeypatch.setitem(D.RUTAS, ZZ, {"url": base + "/models", "forma": "openai"})
    monkeypatch.setitem(cm._PICKER_HOSTEADO, f"api.{ZZ}",
                        {"picker_id": f"api:{ZZ}", "model": "zz-grande",
                         "base_url": base, "byok_ref": f"keys:{ZZ}"})
    fila = cm._h(cm.API, ZZ, "ZZ de prueba", ZZ, None, "un proveedor ficticio", "grande",
                 ["texto"])
    monkeypatch.setattr(cm, "HOSTEADOS", list(cm.HOSTEADOS) + [fila])
    monkeypatch.setattr(cm, "_HOSTEADO_POR_SLUG",
                        {**cm._HOSTEADO_POR_SLUG, fila["slug"]: fila})
    yield {"base": base, "slug": f"api.{ZZ}", "srv": srv}
    srv.shutdown()


def test_ZZ_un_proveedor_nuevo_entra_como_FILA_y_el_sistema_lo_trata_igual(
        proveedor_ficticio, monkeypatch):
    """★★★ LA PRUEBA DURA DE LA LEY. Todo esto tiene que andar sin tocar una línea fuera de
    las tablas: aparece · pide llave · descubre · elige default · se puede cambiar · la
    sonda corre."""
    from app.phase1 import motor_verdad as MV
    from app.phase1 import modelos_discovery as D
    slug, base = proveedor_ficticio["slug"], proveedor_ficticio["base"]

    # 1 · APARECE en la pantalla, como una vía de API más
    filas = cm.filas()["filas"]
    zz = next((f for f in filas if f["slug"] == slug), None)
    assert zz is not None, "el proveedor declarado NO aparece: hay un caso especial en el medio"
    assert zz["familia"] == cm.API

    # 2 · PIDE LLAVE — sin credencial no se corona nada
    assert zz["hay_llave"] in (False, None)
    assert zz["estado"] in (cm.NO_CONFIGURADO, cm.DETECTADO)

    # 3 · DESCUBRE su catálogo con la llave, por el dialecto declarado
    cat = D.descubrir(ZZ, key="zz-buena", fresco=True)
    assert cat["fuente"] == "red", cat
    assert {m["model_id"] for m in cat["modelos"]} == {"zz-grande", "zz-chico", "zz-voz"}

    # 4 · ELIGE UN DEFAULT SENSATO: el más grande SERVIBLE (la voz no es cerebro)
    assert D.elegir(cat) == "zz-grande"
    assert not D.servible(next(m for m in cat["modelos"] if m["model_id"] == "zz-voz"))

    # 5 · SE PUEDE CAMBIAR el modelo, y lo que no sirve se rechaza con SU motivo
    pref = cm.guardar_preferencias({"slug": slug, "modelo": "zz-chico"}, filas)
    assert pref["modelos"][slug] == "zz-chico"
    with pytest.raises(cm.HTTPException) as exc:
        cm.guardar_preferencias({"slug": slug, "modelo": "zz-voz"}, filas)
    assert "Genera voz; no genera texto." in str(exc.value.detail), str(exc.value.detail)

    # 6 · LA SONDA CORRE contra su ruta de generación, y discrimina
    v = MV._KEY_VALIDATORS[ZZ]
    buena = MV.veredicto_key(ZZ, "zz-buena", base=v["base"], header="bearer",
                             modelo="zz-grande")
    assert buena["estado"] == MV.PROBADO, buena
    assert (buena["evidencia"] or {}).get("prueba") == "auth_generacion"
    mala = MV.veredicto_key(ZZ, "no-empieza-con-zz", base=v["base"], header="bearer",
                            modelo="zz-grande")
    assert mala["estado"] == MV.ROTO and mala["causa"] == MV.KEY_INVALIDA


def test_ZZ_no_hace_falta_tocar_las_tablas_OPCIONALES(proveedor_ficticio):
    """Y esto es lo que la vara MIDE de paso: cuáles tablas son OBLIGATORIAS.

    ZZ se dio de alta SIN `MODELO_PRUEBA`, SIN `KEY_SHAPE` y SIN `NOMBRE_MARCA` —las tres
    incompletas hoy para proveedores reales— y todo lo de arriba anda igual. O sea: son
    opcionales de verdad, no «falta cargarlas»."""
    from app.phase1 import motor_verdad as MV
    from app.phase1 import centro_conexiones as CX
    assert ZZ not in MV.MODELO_PRUEBA
    assert ZZ not in CX.KEY_SHAPE
    assert ZZ not in CX.NOMBRE_MARCA


def test_ningun_if_por_nombre_de_proveedor_en_el_camino_de_modelos():
    """★★★ EL GUARD ESTÁTICO de la ley — hermano del ficticio.

    El de ZZ caza el `if` que le toca SU camino. Éste caza el patrón donde ZZ no llega:
    una comparación por NOMBRE de proveedor en cualquier parte de la vía. Los dos hacen
    falta — un `if` en un rincón que ZZ no pisa seguiría siendo un caso especial esperando
    al próximo proveedor."""
    import re
    from pathlib import Path as _P
    raiz = _P(cm.__file__).parent
    archivos = ["motor_verdad.py", "modelos_discovery.py", "centro_modelos.py",
                "centro_conexiones.py"]
    conocidos = ("groq", "openai", "openrouter", "anthropic", "gemini", "mistral",
                 "deepseek", "together")
    patron = re.compile(
        r"(provider|provider_id|ref|proveedor)\s*(==|!=)\s*[\"'](" + "|".join(conocidos) + r")[\"']")
    hits = []
    for nombre in archivos:
        for n, ln in enumerate((raiz / nombre).read_text(encoding="utf-8").splitlines(), 1):
            sin_comentario = ln.split("#", 1)[0]
            if patron.search(sin_comentario):
                hits.append(f"{nombre}:{n}: {ln.strip()[:90]}")
    assert not hits, (
        "LEY: los proveedores son DATOS, no código. Estas líneas comparan por NOMBRE:\n  "
        + "\n  ".join(hits)
        + "\nSi de verdad hace falta, va como COLUMNA de la tabla declarada.")


def test_un_alta_incompleta_NO_se_degrada_en_silencio():
    """★★ Un proveedor dado de alta en algunas tablas y no en todas no rompe nada
    ruidosamente: se DEGRADA EN SILENCIO. Este guard lo nombra.

    Exige las CUATRO obligatorias para toda vía de API, y falla diciendo QUÉ TABLA falta —
    no «algo anda mal». Las opcionales quedan declaradas COMO opcionales en el código
    (`TABLAS_DE_PROVEEDOR`) para que nadie las crea obligatorias ni al revés."""
    from app.phase1 import motor_verdad as MV
    from app.phase1 import modelos_discovery as D

    presencia = {
        "motor_verdad._KEY_VALIDATORS": set(MV._KEY_VALIDATORS),
        "modelos_discovery.RUTAS": set(D.RUTAS),
        "centro_modelos._PICKER_HOSTEADO": {s.split(".", 1)[1] for s in cm._PICKER_HOSTEADO
                                            if s.startswith("api.")},
        "centro_modelos.HOSTEADOS": {h["ref"] for h in cm.HOSTEADOS
                                     if h["familia"] == cm.API},
    }
    assert set(presencia) == set(cm.TABLAS_DE_PROVEEDOR["obligatorias"]), (
        "la declaración de tablas obligatorias y lo que este guard mide se separaron")

    de_api = {h["ref"] for h in cm.HOSTEADOS if h["familia"] == cm.API}
    faltantes = {}
    for ref in sorted(de_api):
        faltan = [t for t, refs in presencia.items() if ref not in refs]
        if faltan:
            faltantes[ref] = faltan
    assert not faltantes, (
        "ALTAS INCOMPLETAS — estos proveedores no están en todas las tablas OBLIGATORIAS y "
        "se degradan en silencio:\n  "
        + "\n  ".join(f"{r} → falta en {', '.join(t)}" for r, t in faltantes.items()))


def test_las_opcionales_estan_declaradas_COMO_opcionales(proveedor_ficticio):
    """Y que sean opcionales no es una opinión: el proveedor ficticio corre sin ninguna de
    las tres, y hace todo lo que tiene que hacer (la vara de ZZ lo prueba). La declaración
    del código dice lo mismo que la medición."""
    from app.phase1 import motor_verdad as MV
    from app.phase1 import centro_conexiones as CX
    opcionales = cm.TABLAS_DE_PROVEEDOR["opcionales"]
    assert set(opcionales) == {"motor_verdad.MODELO_PRUEBA", "centro_conexiones.KEY_SHAPE",
                               "centro_conexiones.NOMBRE_MARCA"}
    # ninguna de las tres tiene a ZZ, y ZZ funciona: la declaración es cierta
    assert ZZ not in MV.MODELO_PRUEBA and ZZ not in CX.KEY_SHAPE and ZZ not in CX.NOMBRE_MARCA
    # …y cada una dice QUÉ pasa sin ella, para que la ausencia tenga camino declarado
    for tabla, porque in opcionales.items():
        assert len(porque) > 20, f"{tabla} no dice qué pasa sin ella"


def test_un_cache_de_OTRA_forma_se_descarta_y_no_se_sirve_a_medias(tmp_path, monkeypatch):
    """★★ LO CAZÓ LA CERTIFICACIÓN SOBRE EL BINARIO INSTALADO, y era invisible desde acá.

    F9 sumó `salidas` a §11, pero el caché en disco seguía siendo el de la forma VIEJA. Los
    modelos cacheados llegaban sin `salidas` y el rechazo perdía su copy sellado —«Genera
    voz; no genera texto.»— cayendo al genérico. El usuario habría visto un copy peor por
    una razón que no existe."""
    from app.phase1 import modelos_discovery as D
    monkeypatch.setattr(D, "_dir_cache", lambda: tmp_path)

    viejo = {"provider_id": "groq", "descubierto_en": "2026-08-01T00:00:00", "modelos": [
        {"provider_id": "groq", "model_id": "zz", "label": "ZZ", "context": 1,
         "capacidades": [], "free": False}]}          # ← sin `salidas`: la forma vieja
    (tmp_path / "groq.json").write_text(json.dumps(viejo), encoding="utf-8")
    assert D._leer_cache("groq") is None, (
        "un caché de otra forma se está SIRVIENDO: sus modelos llegan sin los campos que la "
        "forma nueva trajo, y el producto degrada sin decir por qué")

    # …y lo que ESTE build escribe sí se relee: el descarte es por versión, no por paranoia
    D._escribir_cache("groq", viejo)
    vuelta = D._leer_cache("groq")
    assert vuelta is not None and vuelta["forma_v"] == D.FORMA_V

    # ⚠️ NO SE REPARA NI SE COMPLETA. Rellenar `salidas` con un default sería inventar el
    # dato que la forma nueva vino a traer — y el copy volvería a mentir, ahora en silencio.
    (tmp_path / "groq.json").write_text(json.dumps({**viejo, "forma_v": 1}), encoding="utf-8")
    assert D._leer_cache("groq") is None


# ══════════════════════════════════════════════════════════════════════════════════
# [F9] TEXTO Y LUZ SALEN DEL MISMO CAMPO — no pueden discrepar por construcción
# ══════════════════════════════════════════════════════════════════════════════════
def _sesiones(actual=True, ready=True, service="ready"):
    est = "ready" if ready else "no_auth"
    return {"providers": {"claude_cli": {"provider": "claude_cli", "state": est,
                                         "detail": "sesión activa (max)"}},
            "service": {"state": service, "detail": "listener"},
            "actual": actual, "persistida": not actual, "ts": 1786100000.0}


def _fila_cli(estado="probado"):
    return {"filas": [{"slug": "cli.claude_cli", "familia": cm.CLI, "ref": "claude_cli",
                       "label": "Claude Code", "estado": estado, "causa": None,
                       "local": False,
                       "prueba": {"estado": "probado", "ts": 1786100000.0,
                                  "detalle": "sesión activa (max)"}}]}


def test_una_fila_NUNCA_dice_probado_y_desconectado_a_la_vez(v2_env):
    """★★ EL BUG MEDIDO EN LA APP (payload real de `/v1/modelos/v2`, 2026-08-07):

        estado: "probado"   ← de ahí salía el texto «probado hace 0s»
        conectado: FALSE    ← de ahí salía la luz GRIS

    En la MISMA lista, Claude Code y Codex en gris y OpenRouter en verde, los tres con el
    mismo texto. La fila traía DOS VERDADES desde el origen: `estado` del motor (con
    evidencia y fecha) y `conectado` de un sensor propio de la vía CLI — la sonda de sesión
    VIVA. Con `actual:false` (snapshot persistido) esa sonda no corre, ninguna rama toca
    `estado`, y `conectado` cae a False por AUSENCIA DE MEDICIÓN.

    Es la regla sellada otra vez: ausencia de registro no es dato negativo."""
    f = cm._anotar_conectados(_fila_cli("probado"), _sesiones(actual=False))["filas"][0]
    assert f["estado"] == cm.PROBADO
    assert f["conectado"] is True, (
        "la fila dice «probado» y «desconectado» a la vez: el texto y la luz vienen de dos "
        "campos que pueden discrepar")


def test_con_sonda_viva_manda_la_sonda_y_los_dos_campos_siguen_de_acuerdo(v2_env):
    """La sonda viva sigue siendo la medición buena cuando corre — lo que se sacó es el
    SEGUNDO sensor de `conectado`, no la medición."""
    viva = cm._anotar_conectados(_fila_cli("detectado"), _sesiones(actual=True))["filas"][0]
    assert viva["estado"] == cm.PROBADO and viva["conectado"] is True, viva

    rota = cm._anotar_conectados(_fila_cli("probado"),
                                 _sesiones(actual=True, ready=False))["filas"][0]
    assert rota["estado"] == cm.ROTO and rota["conectado"] is False, (
        "con sesión caída la sonda MANDA: baja el estado, y la luz lo sigue")
    assert rota["causa"] == cm.MV.SIN_SESION


def test_la_regla_de_conectado_es_UNA_por_via_y_esta_declarada(v2_env):
    """Cada vía puede tener REQUISITOS propios (la API su llave, la local su tag) — eso no
    es un segundo sensor del mismo hecho, es un requisito real. Lo que no puede haber es
    dos formas de responder «¿está conectada?» para la MISMA vía."""
    import re
    from pathlib import Path as _P
    fuente = (_P(cm.__file__)).read_text(encoding="utf-8")
    i = fuente.index("def _anotar_conectados")
    cuerpo = fuente[i:i + 4200]
    # `conectado` se ASIGNA sólo derivándolo del estado (más los requisitos declarados)
    asignaciones = [ln.strip() for ln in cuerpo.splitlines()
                    if re.match(r"\s*conectado = ", ln)]
    assert asignaciones, "no se encontró la derivación"
    for a in asignaciones:
        assert "estado" in a or a == "conectado = False", (
            f"`conectado` se decide sin mirar `estado`: {a!r} — ése es el segundo sensor "
            f"que hace que el texto y la luz puedan discrepar")
