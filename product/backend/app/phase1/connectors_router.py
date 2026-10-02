"""
connectors_router.py — endpoints del connect-wizard (D2), GENÉRICOS.

Exponen por HTTP el `connect_engine` (cero código por-conector) + sirven los onboarding
objects. Una sola pieza cubre los 13 conectores + futuros:

  GET  /v1/connectors                 → lista (connector, auth_method, tier, capability)
  GET  /v1/connectors/{name}           → el onboarding object v3 completo (lo que renderiza el wizard)
  POST /v1/connectors/{name}/connect   → corre connect_engine: paste → auth → validate → estado
                                          (y, si user_id + connected, guarda la credencial cifrada BYOK)

api_base: del object (conectores globales) o el base_url del user (needs_base_url, self-hosted).
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

try:
    import aleph_paths as _ap
except ImportError:
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "platform"))
    import aleph_paths as _ap

_RESOURCE_ROOT = _ap.resource_root()


def _dos_hechos(slug: str, conexiones: dict, motor: dict, dueno) -> dict:
    """Los tres campos de «probada», derivados de LOS DOS registros que la casa escribe.

    Existe como función y no en línea porque la fusión tiene una regla que hay que poder
    leer de una: **un verde en cualquiera de los dos manda**. Los dos veredictos son
    verdaderos —`conexiones` prueba la pieza equipada con una tool, el motor prueba la
    credencial contra el proveedor— y ninguno de los dos es más «real» que el otro. Que uno
    esté vacío no refuta al otro: dice que esa puerta no pasó por ahí.

    Y `None` NO ES `False`. `None` = nadie probó nunca (o no hay sesión para saberlo).
    `False` = se probó y no dio verde, y entonces `falla` dice por qué. Pintarlos igual es
    volver al `connected = len(set) > 0` que esta obra vino a matar.
    """
    if not dueno:
        return {"verificado": None, "verificado_cuando": None,
                "verificado_con": None, "verificado_falla": None}
    # ⚠️ UNA FILA SIN VEREDICTO ES UNA FILA SIN VEREDICTO, NO UN VEREDICTO NEGATIVO.
    # Medido contra el vault real: `exa` tiene fila en `conexiones` con `credencial: null`
    # —la fila existe porque la pieza está en el registro, no porque alguien la haya probado—
    # y este código la tomaba como «se probó y no dio verde»: devolvía `False`. La cara la
    # pintaba «Guardada» igual, así que no llegó a mentirle a nadie; pero el CAMPO mentía, y
    # el docstring de acá arriba declara lo contrario. Un `False` que en realidad es «no sé»
    # es el mismo error que esta obra vino a matar, con el signo cambiado.
    #
    # `presente` = el registro tiene algo que DECIR de esta pieza. Sin `estado` (o sin
    # `probada` en el del motor), no lo tiene.
    def presente(reg):
        if not reg:
            return False
        return bool(reg.get("probada")) or reg.get("estado") is not None or reg.get("falla")
    cx = conexiones.get(slug) or {}
    mv = motor.get(slug) or {}
    if not presente(cx) and not presente(mv):
        return {"verificado": None, "verificado_cuando": None,
                "verificado_con": None, "verificado_falla": None}
    # A partir de acá sólo pesan los registros que tienen algo que decir: uno mudo no puede
    # ganarle a uno que habló, ni aportar su fecha vacía.
    if not presente(cx):
        cx = {}
    if not presente(mv):
        mv = {}
    # El verde manda, y con él viajan SU fecha y SU evidencia: mezclar la fecha de un
    # registro con la evidencia del otro sería fabricar un veredicto que nadie emitió.
    gana = cx if cx.get("probada") else (mv if mv.get("probada") else (cx or mv))
    return {
        "verificado": bool(gana.get("probada")),
        "verificado_cuando": gana.get("cuando"),
        "verificado_con": gana.get("con"),
        # La causa cruda: la traduce `CAUSAS_HUMANAS` en la cara. Sólo el motor la tiene —
        # `conexiones` guarda estados (`verde`/`rechazada`), no causas del vocabulario.
        "verificado_falla": (gana.get("falla") if not gana.get("probada") else None),
    }


def _recomendaciones() -> dict:
    """`catalog/connectors/workspace-recommendations.json`, o un vacío que SE DECLARA vacío.

    Por `resource_root()` y no por una ruta relativa: es la lección que costó el defecto de la
    tabla de alias en F1 —adentro del `.app` el árbol no está donde el dev cree— y el
    resolvedor frozen-safe de la casa es éste.

    Si el archivo no está, se devuelve `{"_origen": "sin_tabla"}` y NO un dict vacío pelado: la
    cara tiene que poder distinguir «ningún conector se recomienda acá» de «no pude leer la
    tabla». Un rojo mudo es peor que un rojo que habla.
    """
    ruta = _RESOURCE_ROOT / "catalog" / "connectors" / "workspace-recommendations.json"
    try:
        d = json.loads(ruta.read_text(encoding="utf-8"))
        if not (d.get("recomendaciones") or {}):
            return {"_origen": "tabla_vacia", "workspaces": d.get("workspaces") or []}
        d["_origen"] = "catalogo"
        return d
    except Exception:                               # noqa: BLE001 — frontera de disco
        return {"_origen": "sin_tabla", "workspaces": [], "recomendaciones": {}}
_ONB = _RESOURCE_ROOT / "catalog" / "connectors" / "onboarding"
_ENGINE_PY = _RESOURCE_ROOT / "platform" / "connectors" / "connect_engine.py"
_OAUTH_PY = _RESOURCE_ROOT / "platform" / "connectors" / "oauth_flow.py"
_LOOPBACK_PY = _RESOURCE_ROOT / "platform" / "connectors" / "oauth_loopback.py"

# State CSRF de un solo uso (best-effort, in-proc): rechaza un replay del MISMO state
# dentro de la vida del proceso. La protección anti-forja la da el Fernet (read_state);
# esto sólo cierra el replay. Se resetea al reiniciar — follow-up: persistir/TTL si hace falta.
_used_states: set[str] = set()


def _engine():
    return _ap.load_module_by_path("puppet_connect_engine", _ENGINE_PY)


def _oauth():
    return _ap.load_module_by_path("puppet_oauth_flow", _OAUTH_PY)


def _oauth_loopback():
    return _ap.load_module_by_path("puppet_oauth_loopback", _LOOPBACK_PY)


def _oauth_env() -> dict:
    """env del proceso + fallback a infra/.env — así las creds OAuth funcionan apenas se
    peguen al .env, sin depender de cómo se inyecta el env al :8080. El env del proceso
    SIEMPRE gana; el .env sólo rellena lo ausente. Sólo se usan client_id/secret de acá."""
    env = dict(os.environ)
    dotenv = _RESOURCE_ROOT / "infra" / ".env"
    if dotenv.exists():
        try:
            for line in dotenv.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if v and not env.get(k):
                    env[k] = v
        except OSError:
            pass
    return env


def _redirect_uri(name: str) -> str:
    """El redirect_uri DEBE coincidir exacto con el registrado en el proveedor.

    review F8 · resolvemos la base por _oauth_env() (proceso + fallback infra/.env), IGUAL que las
    client creds. Antes leía sólo os.environ: un deploy que pone TODO en infra/.env obtenía creds
    válidas pero un redirect_uri localhost por defecto → mismatch con el registrado → el flujo OAuth
    fallaba entero. Ahora ambas mitades salen de la misma fuente."""
    base = (_oauth_env().get("PUPPET_OAUTH_REDIRECT_BASE") or "http://localhost:8080").rstrip("/")
    return f"{base}/v1/connectors/{name}/callback"


def _spa_base() -> str:
    return (os.environ.get("PUPPET_SPA_BASE") or "http://localhost:8091").rstrip("/")


class ConnectRequest(BaseModel):
    creds: dict[str, Any]                 # {credential_field_id: valor pegado}
    base_url: Optional[str] = None        # solo si needs_base_url (self-hosted)
    user_id: Optional[str] = None         # si viene + connected → guarda BYOK cifrado


def build_connectors_router(*, get_conn: Optional[Callable[[], Any]] = None) -> APIRouter:
    router = APIRouter(prefix="/v1/connectors", tags=["connectors"])
    eng = _engine()
    oauth = _oauth()
    loopback = _oauth_loopback().LoopbackFlowManager()

    def _load(name: str) -> dict:
        p = _ONB / f"{name}.json"
        if not p.exists():
            raise HTTPException(status_code=404, detail=f"conector '{name}' no encontrado")
        return json.loads(p.read_text(encoding="utf-8"))

    def _owner(authorization: Optional[str]) -> str:
        from app.phase1 import repo
        tok = authorization.strip() if authorization else ""
        if tok.lower().startswith("bearer "):
            tok = tok[7:].strip()
        owner = repo.session_owner(tok)
        if owner is None:
            raise HTTPException(status_code=401, detail={
                "error": "no_session", "detail": "Inicia sesión para conectar OAuth.",
            })
        return str(owner)

    def _store_oauth(name: str, user_id: str, cfg: dict, res: dict,
                     display_name: Optional[str] = None) -> dict:
        """Persiste access + refresh + scopes concedidos en el vault global cifrado."""
        label = str(display_name or name)
        if get_conn is None:
            return {"state": "exchange_failed", "cause": "vault_unavailable",
                    "message": "El vault cifrado no está disponible."}
        from app.phase1 import repo
        granted = oauth.normalize_granted_scopes(res.get("granted_scopes"))
        tools = oauth.tools_for_granted_scopes(cfg, granted)
        durable = bool(res.get("refresh_token")) or not cfg.get("refresh_required")
        connection_state = "connected" if durable else "oauth_partial"
        # `expira_en` ABSOLUTO, igual que el callback del Caso A. Guardar sólo el par
        # relativo es el bug que ese camino ya pagó: al releerlo no se sabe CUÁNDO empezó a
        # contar y un token muerto pasa por vivo. `expires_in`/`obtained_at` quedan por
        # compatibilidad con los companions ya escritos.
        _exp = res.get("expires_in")
        _ahora_ts = time.time()
        companion = {
            "schema_version": 2,
            "provider": name,
            "state": connection_state,
            "refresh_token": res.get("refresh_token"),
            "expires_in": _exp,
            "obtained_at": _ahora_ts,
            "expira_en": (_ahora_ts + float(_exp)) if _exp else None,
            "token_url": cfg.get("token_url"),
            "granted_scopes": granted,
            "scope_source": res.get("scope_source") or "missing",
        }
        conn = get_conn()
        try:
            repo.upsert_key(conn, user_id=user_id, provider=name,
                            secret=res["access_token"])
            # El companion existe aun si no vino refresh: ahí vive el scope CONCEDIDO,
            # cifrado igual que los tokens, y la superficie del belt falla cerrada.
            repo.upsert_key(conn, user_id=user_id, provider=f"{name}__oauth",
                            secret=json.dumps(companion))
            try:
                repo.delete_key(conn, user_id=user_id,
                                provider=f"{name}__oauth_partial")
            except Exception:
                pass
        finally:
            conn.close()
        if not durable:
            message = (f"{label} no devolvió refresh_token; el acceso es parcial "
                       "y necesita reconexión antes de expirar.")
        elif granted:
            message = f"{label} quedó conectado."
        else:
            message = (f"{label} conectó, pero no informó scopes concedidos; "
                       "las tools quedan ocultas.")
        return {
            "state": connection_state, "message": message,
            "granted_scopes": granted, "scope_source": companion["scope_source"],
            "tools": tools,
        }

    def _loopback_begin(name: str, obj: dict, user_id: str) -> dict:
        cfg = oauth.oauth_cfg(obj)
        label = str(obj.get("provider") or name)
        cid, csec = oauth.client_creds(cfg, _oauth_env())
        if not cid:
            return {"state": "oauth_unconfigured", "provider": name,
                    "cause": "missing_client_id",
                    "message": "La entrada de catálogo no tiene client_id."}
        if cfg.get("client_auth") == "secret_post" and not csec:
            return {
                "state": "account_required", "provider": name,
                "cause": "confidential_exchange_required",
                "message": (f"{label} exige un secreto para canjear el código. "
                            "Este conector necesita una cuenta de Aleph."),
            }

        def _on_code(code: str, verifier: str) -> dict:
            result = oauth.exchange_code(
                cfg, client_id=cid, client_secret=csec, code=code,
                redirect_uri=str(cfg["redirect_uri"]), code_verifier=verifier,
            )
            if not result.get("ok"):
                err = result.get("error")
                if err in ("invalid_client", "unauthorized_client"):
                    return {
                        "state": "exchange_failed", "cause": "invalid_client_id",
                        "message": (f"{label} rechazó la app de Aleph. Revisa el client_id "
                                    "del catálogo y la app registrada."),
                    }
                return {
                    "state": "exchange_failed", "cause": err or "token_exchange",
                    "message": result.get("error_description")
                               or f"{label} rechazó el canje del código.",
                }
            return _store_oauth(name, user_id, cfg, result, label)

        try:
            return loopback.start(
                provider=name, owner=user_id, cfg=cfg, client_id=cid,
                build_authorize_url=oauth.build_authorize_url,
                on_code=_on_code,
                timeout=float(cfg.get("loopback_timeout_seconds") or 180),
            )
        except ValueError as exc:
            return {"state": "oauth_config_error", "provider": name,
                    "cause": str(exc).split(":", 1)[0],
                    "message": f"Configuración OAuth inválida: {str(exc)[:160]}"}
        except RuntimeError as exc:
            cause = str(exc)
            return {
                "state": "loopback_unavailable", "provider": name, "cause": cause,
                "message": ("Ya hay un OAuth en curso." if cause == "oauth_flow_in_progress"
                            else "No pude abrir localhost:8765; cierra el proceso que usa ese puerto."),
            }

    def _oauth_begin(name: str, obj: dict, user_id: Optional[str]) -> dict:
        """Caso A · arranque del handoff: arma el authorize_url (con state CSRF) o, si la
        app OAuth de Puppet no está registrada, conserva oauth_pending (botón honesto, no muerto)."""
        if not user_id:
            return {"state": "oauth_pending", "provider": obj.get("provider", name),
                    "message": "Inicia sesión para conectar tu cuenta."}
        cfg = oauth.oauth_cfg(obj)
        # Un `redirect_uri` en el descriptor ES la declaración de que este conector va por
        # loopback (Caso desktop). El Caso A clásico —redirect al backend— sigue abajo.
        if cfg.get("redirect_uri"):
            return _loopback_begin(name, obj, str(user_id))
        cid, csec = oauth.client_creds(cfg, _oauth_env())
        if not (cid and csec and cfg.get("authorize_url")):
            return {"state": "oauth_pending", "provider": obj.get("provider", name),
                    "message": (cfg.get("unconfigured_message")
                                or f"Conectar con {name} requiere registrar la app OAuth de Aleph (con aprobación).")}
        from app.phase1 import repo
        state = oauth.mint_state(repo.encrypt_secret, user_id=user_id, provider=name)
        url = oauth.build_authorize_url(cfg, client_id=cid,
                                        redirect_uri=_redirect_uri(name), state=state)
        return {"state": "oauth_redirect", "provider": obj.get("provider", name),
                "authorize_url": url}

    @router.get("")
    def list_connectors(workspace: Optional[str] = None,
                        user_id: Optional[str] = None,
                        authorization: Optional[str] = Header(default=None)):
        """El catálogo curado, con su recomendación por workspace y el estado del usuario.

        ⚠️ UN ENDPOINT, N VISTAS — y es la razón de que la recomendación se sirva acá y no la
        resuelva cada pantalla. Las dos superficies que la van a usar (la vista general de
        Conectores y la de cada canvas) leen ESTO. Si cada una resolviera su propia lista,
        configurar `github` en Ciencia podría verse «sin configurar» en Diseño, y eso sería la
        cara mintiendo sobre el destino — que es exactamente lo que la tabla de recomendaciones
        existe para evitar.

        ⚠️ Y `tiene_llave` NO ES `verificado`. Son dos hechos distintos y se sirven separados a
        propósito: juntarlos es la mentira que Ciencia midió, donde `connected: set.length > 0`
        pintaba «conectado» sobre un campo que el stack no podía descifrar, con el env vacío y
        0 líneas de log. Acá:
          · `tiene_llave`  — el vault del usuario tiene una credencial con ese nombre. Un hecho
                             de almacenamiento, y nada más.
          · `verificado`   — hay un veredicto PERSISTIDO de la única puerta que verifica y
                             escribe (`MV.probar`, con evidencia y fecha). `None` = nadie probó,
                             que no es lo mismo que «falló».
        La pantalla puede decir «configurado» con el primero y «probado» sólo con el segundo.
        """
        recos = _recomendaciones()
        pedido = (workspace or "").strip().lower() or None
        if pedido and pedido not in (recos.get("workspaces") or []):
            raise HTTPException(status_code=422, detail={
                "error": "workspace_desconocido",
                "detail": f"«{pedido}» no es un workspace. Son: "
                          + ", ".join(recos.get("workspaces") or [])})

        # EL DUEÑO SÓLO SI HAY SESIÓN. Sin sesión el catálogo se sirve igual (es público) pero
        # sin estado: `tiene_llave` queda en None, que la cara tiene que leer como «no sé», no
        # como «no». Un `False` sin sesión sería decirle «no configurado» a alguien que quizá
        # lo tiene configurado.
        dueno = None
        if user_id:
            from app.phase1 import repo
            tok = authorization.strip() if authorization else None
            if tok and tok.lower().startswith("bearer "):
                tok = tok[7:].strip()
            owner = repo.session_owner(tok)
            if owner is None:
                raise HTTPException(status_code=401, detail={
                    "error": "no_session", "detail": "Inicia sesión para ver tus conexiones."})
            if str(owner) != str(user_id):
                raise HTTPException(status_code=403, detail={
                    "error": "forbidden", "detail": "Esa cuenta no es la tuya."})
            dueno = owner

        llaves: set = set()
        # EL SEGUNDO HECHO, QUE FALTABA SERVIR. Documenté que `tiene_llave` no es `verificado`
        # y después serví sólo el primero: la pantalla decía «Listo» sobre una credencial que
        # nadie probó nunca. Medido en el vault real — `exa` tenía llave con
        # `ultimo_veredicto=None` y `credencial=None`, y `zotero` tenía
        # `credencial={"estado":"verde","tool_prueba":"whoami","ts":…}`. Los dos se pintaban
        # igual. Es el mismo `connected=True` que medí en Ciencia, repetido por omisión.
        #
        # El veredicto se lee de `conexiones` con `listar_entidades`, que ya es SU lector: no
        # se escribe una tercera consulta sobre la misma tabla.
        veredictos: dict = {}
        if dueno and get_conn is not None:
            from app.phase1 import repo
            try:
                with get_conn() as _c:
                    llaves = {str(k.get("provider")) for k in repo.list_keys(_c, dueno)}
                    from app.phase1 import conexiones_repo as _cx
                    for ent in _cx.listar_entidades(_c, dueno):
                        cred = ent.get("credencial")
                        if isinstance(cred, str):
                            try:
                                cred = json.loads(cred)
                            except Exception:       # noqa: BLE001 — dato viejo sin forma
                                cred = None
                        estado = (cred or {}).get("estado") if isinstance(cred, dict) else None
                        veredictos[str(ent.get("entity_id"))] = {
                            # `verde` es el único que cuenta como probada. Cualquier otro
                            # valor —o su ausencia— NO es «falló»: es «nadie probó».
                            "probada": estado == "verde",
                            "estado": estado,
                            "cuando": (cred or {}).get("ts") if isinstance(cred, dict) else None,
                            "con": (cred or {}).get("tool_prueba") if isinstance(cred, dict) else None,
                        }
            except Exception:                       # noqa: BLE001 — frontera de DB
                # FALLO VISIBLE, JAMÁS MUDO: si no se pudo leer el vault, no se finge un
                # «no configurado». Se deja `tiene_llave=None` y la cara dice «no sé».
                llaves = set()
                veredictos = {}
                dueno = None

        # EL OTRO REGISTRO, Y NO ES REDUNDANCIA: MEDIDO HOY, HAY DOS PUERTAS DE GUARDADO Y
        # NO ESCRIBEN EN EL MISMO LUGAR.
        #   · `POST /v1/conexiones/key` (la del catálogo) → `agregar_key` prueba la llave con
        #     `MV.veredicto_key`, siembra el motor, y detrás del response corre `verificar_uno`
        #     sobre las filas EQUIPADAS → deja el veredicto en `conexiones.credencial`.
        #   · `POST /v1/connectors/<slug>/connect` (la puerta de ESTA vista) → dispara
        #     `motor_verdad.al_conectar`, que es `MV.probar`, y NO toca `conexiones`.
        # O sea que leer sólo `conexiones` dejaba en «Guardada» para siempre a toda llave
        # puesta desde Recomendados, aunque al guardarla se hubiera probado de verdad. El
        # registro del motor es el que alimentan LAS DOS, así que es el que manda; `conexiones`
        # suma el veredicto de las piezas equipadas, que el motor no tiene.
        #
        # ⚠️ ES `estado`, NO `probar`. Lectura del caché persistido: no spawnea, no sale a la
        # red, no cuesta tokens, y su contrato es explícito — «nunca verde sin evidencia».
        # Llamar a `probar` acá convertiría pintar una lista de 29 en 29 pruebas contra
        # proveedores reales cada vez que alguien abre la pantalla.
        motor: dict = {}
        if dueno and llaves:
            try:
                from app.phase1 import motor_verdad as _MV
                for _prov in llaves:
                    st = _MV.estado(_MV.KEY, _prov, owner=dueno) or {}
                    if not st.get("cacheado"):
                        continue                    # nadie probó: se deja en «no sé», no en «no»
                    ev = st.get("evidencia") or {}
                    ts = st.get("probado_ts") or st.get("ts")
                    motor[_prov] = {
                        "probada": st.get("estado") == _MV.PROBADO,
                        # La causa viaja CRUDA y la cara la traduce con `CAUSAS_HUMANAS`, que
                        # es el diccionario sellado del semáforo. Una segunda tabla de copy es
                        # cómo la misma falla se lee distinto según la pantalla.
                        "falla": st.get("causa") if st.get("estado") == _MV.ROTO else None,
                        "cuando": (time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(float(ts)))
                                   if ts else None),
                        "con": (ev.get("modelo_probado")
                                or ("una llamada autenticada"
                                    if ev.get("prueba") == "catalogo_autenticado" else None)),
                    }
            except Exception:                       # noqa: BLE001 — el registro del motor es
                # UN SEGUNDO HECHO, NO EL PRIMERO: si no se puede leer, la lista se sirve
                # igual con `tiene_llave`. Perder el «Probada» es una etiqueta menos; perder
                # la lista entera por eso sería cambiar un dato de más por la pantalla.
                motor = {}

        out = []
        for p in sorted(_ONB.glob("*.json")):
            try:
                o = json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            slug = p.stem
            rec = (recos.get("recomendaciones") or {}).get(slug) or {}
            en = list(rec.get("en") or [])
            if pedido and pedido not in en:
                continue
            out.append({
                "connector": o.get("connector"),
                "slug": slug,
                "auth_method": o.get("auth_method"),
                "tier": o.get("tier"),
                "needs_base_url": o.get("needs_base_url", False),
                "capability_line": o.get("capability_line"),
                "capability_line_i18n": {"es": o.get("capability_line") or "",
                                         "en": (o.get("en") or {}).get("capability_line") or ""},
                # La recomendación, tal como la declara el catálogo. Lista vacía = decisión de
                # «no va en ninguno», no un hueco (lo garantiza `qa/vara_f1_recomendaciones.py`).
                "workspaces": en,
                "por_que": rec.get("por_que") or "",
                # EL CRUCE, SERVIDO. Que `github` diga 3 es lo que le permite a la cara poner
                # «también en Diseño y Oficina» sin que la pantalla lo deduzca sola.
                "cruza": len(en) > 1,
                "tiene_llave": (slug in llaves) if dueno else None,
                # ⚠️ DOS HECHOS, SERVIDOS APARTE. `verificado` es `None` cuando nadie probó —
                # que NO es lo mismo que «falló»— y trae la fecha y con qué se probó, porque
                # un veredicto sin fecha es afirmar de memoria.
                # LOS DOS REGISTROS, CON EL VERDE MANDANDO. Un `verde` en cualquiera de
                # los dos es un veredicto con evidencia y fecha; que el otro no lo tenga sólo
                # dice que esa puerta no pasó por ahí. Y `None` sigue siendo «nadie probó»,
                # que no es «falló».
                **_dos_hechos(slug, veredictos, motor, dueno),
            })
        return {"connectors": out, "total": len(out),
                "workspace": pedido, "workspaces": recos.get("workspaces") or [],
                # De dónde salió la tabla, para que un 0 de recomendaciones no se confunda con
                # «no hay tabla» — la lección del `sin_tabla` de F1.
                "tabla": recos.get("_origen", "catalogo")}

    @router.get("/{name}")
    def get_connector(name: str):
        return _load(name)

    @router.post("/{name}/connect")
    def connect(name: str, body: ConnectRequest,
                authorization: Optional[str] = Header(default=None)):
        # AUTHZ: si la conexión se atribuye a un user (guardará su BYOK), exigí que sea
        # el de la sesión — un token de otro/ausente no puede guardar creds a su nombre.
        if body.user_id:
            from app.phase1 import repo
            tok = authorization.strip() if authorization else None
            if tok and tok.lower().startswith("bearer "):
                tok = tok[7:].strip()
            owner = repo.session_owner(tok)
            if owner is None:
                raise HTTPException(status_code=401,
                    detail={"error": "no_session", "detail": "Inicia sesión para conectar."})
            if str(owner) != str(body.user_id):
                raise HTTPException(status_code=403,
                    detail={"error": "forbidden", "detail": "Esa cuenta no es la tuya."})
        obj = _load(name)

        # ── Caso A · OAuth (Authorization Code) ────────────────────────────────────
        # oauth no usa paste→validate: arranca el handoff al proveedor (redirect al consent).
        # El user_id ya quedó validado contra la sesión en el bloque de authz de arriba.
        if obj.get("auth_method") == "oauth":
            return _oauth_begin(name, obj, body.user_id)

        api_base = obj.get("api_base") or ""
        if obj.get("needs_base_url"):
            if not body.base_url:
                raise HTTPException(status_code=422,
                                    detail={"error": "base_url_required",
                                            "detail": f"{name} necesita tu dominio primero"})
            api_base = body.base_url.rstrip("/")

        result = eng.connect(obj, body.creds, api_base=api_base)

        # BYOK: si conectó (verde) o quedó sin-poder-verificar (ámbar) y hay user_id, guardar la
        # credencial CIFRADA (nunca plaintext). `connected_unverified` también guarda: la key la trajo
        # el user y se confirma en el primer uso real; no guardarla obligaría a re-pegarla.
        if result.get("state") in ("connected", "connected_unverified") and body.user_id and get_conn is not None:
            try:
                from app.phase1 import repo
                conn = get_conn()
                try:
                    secret = json.dumps(body.creds) if len(body.creds) > 1 else next(iter(body.creds.values()), "")
                    repo.upsert_key(conn, user_id=body.user_id, provider=name, secret=str(secret))
                finally:
                    conn.close()
                result["stored"] = True
                # [MOTOR DE VERDAD · T1 · §2 "Al conectar algo, se prueba solo"] fire-and-forget:
                # la credencial recién guardada se prueba sola en un hilo y queda cacheada; la UI
                # la lee por GET /v1/motor/estado. Best-effort DURO: nunca bloquea ni rompe el
                # connect (un fallo del probe no puede desconectar una key que SÍ se guardó).
                try:
                    import threading as _th
                    from app.phase1 import motor_verdad as _motor
                    _th.Thread(target=lambda: _motor.al_conectar(
                        _motor.KEY, name, owner=body.user_id, get_conn=get_conn),
                        daemon=True).start()
                except Exception:
                    pass
            except Exception as exc:
                result["stored"] = False
                result["store_error"] = str(exc)
        return result

    @router.post("/{name}/oauth/start")
    def oauth_start(name: str,
                    authorization: Optional[str] = Header(default=None)):
        """Contrato para la card: inicia OAuth y devuelve URL + estado observable."""
        owner = _owner(authorization)
        obj = _load(name)
        if obj.get("auth_method") != "oauth":
            raise HTTPException(status_code=409, detail={
                "error": "not_oauth", "detail": f"{name} no usa OAuth.",
            })
        return _oauth_begin(name, obj, owner)

    @router.get("/{name}/oauth/status")
    def oauth_status(name: str,
                     authorization: Optional[str] = Header(default=None)):
        """Estado sin secretos: fuente única para que la card pinte este paso."""
        owner = _owner(authorization)
        obj = _load(name)
        label = str(obj.get("provider") or name)
        cfg = oauth.oauth_cfg(obj)
        active = loopback.status(owner=owner, provider=name)
        if active.get("state") != "idle":
            return active
        if get_conn is None:
            return {"provider": name, "state": "disconnected",
                    "message": f"{label} todavía no está conectado."}
        from app.phase1 import repo
        conn = get_conn()
        try:
            access = repo.get_key(conn, owner, name)
            raw = repo.get_key(conn, owner, f"{name}__oauth")
        finally:
            conn.close()
        if not access:
            return {"provider": name, "state": "disconnected",
                    "message": f"{label} todavía no está conectado."}
        try:
            companion = json.loads(raw or "{}")
        except (TypeError, json.JSONDecodeError):
            companion = {}
        state = str(companion.get("state") or "connected")
        granted = oauth.normalize_granted_scopes(companion.get("granted_scopes"))
        messages = {
            "connected": f"{label} está conectado.",
            "oauth_partial": f"{label} conectó sin refresh durable; reconéctalo.",
            "oauth_revoked": f"Revocaste el acceso desde {label}.",
            "refresh_failed": f"No pude renovar el acceso de {label}.",
        }
        return {
            "provider": name, "state": state,
            "message": messages.get(state, f"{label} necesita reconectarse."),
            "granted_scopes": granted,
            "scope_source": companion.get("scope_source") or "missing",
            "tools": oauth.tools_for_granted_scopes(cfg, granted),
        }

    @router.delete("/{name}/oauth")
    def oauth_disconnect(name: str,
                         authorization: Optional[str] = Header(default=None)):
        """Revocación best-effort en proveedor + borrado local inmediato del vault."""
        owner = _owner(authorization)
        obj = _load(name)
        label = str(obj.get("provider") or name)
        cfg = oauth.oauth_cfg(obj)
        if get_conn is None:
            raise HTTPException(status_code=503, detail={
                "error": "vault_unavailable", "detail": "El vault no está disponible.",
            })
        from app.phase1 import repo
        conn = get_conn()
        try:
            access = repo.get_key(conn, owner, name)
            raw = repo.get_key(conn, owner, f"{name}__oauth")
            try:
                companion = json.loads(raw or "{}")
            except (TypeError, json.JSONDecodeError):
                companion = {}
            token = companion.get("refresh_token") or access
            cid, csec = oauth.client_creds(cfg, _oauth_env())
            provider_result = (oauth.revoke_token(
                cfg, token=token, client_id=cid, client_secret=csec,
            ) if token else {"ok": False, "reason": "not_connected"})
            # El corte local no depende de que el proveedor tenga revoke endpoint.
            for provider in (name, f"{name}__oauth", f"{name}__oauth_partial"):
                try:
                    repo.delete_key(conn, user_id=owner, provider=provider)
                except Exception:
                    pass
        finally:
            conn.close()
        loopback.stop("disconnected")
        return {
            "provider": name, "state": "disconnected",
            "message": f"{label} quedó desconectado de Aleph.",
            "provider_revoked": bool(provider_result.get("ok")),
            "provider_revoke_reason": provider_result.get("reason"),
        }

    @router.get("/{name}/callback")
    def oauth_callback(name: str,
                       code: Optional[str] = None,
                       state: Optional[str] = None,
                       error: Optional[str] = None):
        """Caso A · vuelta del proveedor. ORCID redirige el browser acá (sin Bearer): el
        binding al user viaja DENTRO del state (cifrado). Valida state (CSRF) → intercambia
        code→token server-side → guarda CIFRADO en el broker → 302 de vuelta a la SPA.
        Deny → 302 cancelado (no ✓). Sin state válido → 400 (rechazo duro)."""
        from app.phase1 import repo
        spa = _spa_base()

        def _ret(q: str):
            # review F7 · `name` viene del PATH y se url-decodifica: interpolarlo crudo en la query
            # deja inyectar params (p.ej. name='gmail&oauth=ok' spoofearía un éxito en un flujo
            # cancelado). Lo escapamos igual que `id` más abajo (quote safe='').
            return RedirectResponse(
                f"{spa}/Conectar.dc.html?c={urllib.parse.quote(name, safe='')}&{q}", status_code=302)

        # 1) El usuario DENEGÓ en el consent → cancelado + reintentar (jamás ✓).
        if error:
            return _ret("oauth=cancelled")
        # 2) CSRF: sin un state VÁLIDO para este provider, el callback se rechaza duro.
        user_id = oauth.read_state(repo.decrypt_secret, state, provider=name)
        if not user_id:
            raise HTTPException(status_code=400,
                detail={"error": "bad_state",
                        "detail": "state ausente / inválido / expirado — callback rechazado."})
        if state in _used_states:
            raise HTTPException(status_code=400,
                detail={"error": "replay", "detail": "ese state ya se usó."})
        if not code:
            raise HTTPException(status_code=400,
                detail={"error": "no_code", "detail": "callback sin code."})
        # 3) Intercambio code→token (server-side; el secret nunca tocó el browser).
        obj = _load(name)
        cfg = oauth.oauth_cfg(obj)
        cid, csec = oauth.client_creds(cfg, _oauth_env())
        if not (cid and csec):
            return _ret("oauth=error&reason=unconfigured")
        res = oauth.exchange_code(cfg, client_id=cid, client_secret=csec,
                                  code=code, redirect_uri=_redirect_uri(name))
        if not res.get("ok"):
            return _ret("oauth=error&reason=exchange")
        # 4) Token CIFRADO al broker (SOLO acá, post-callback). Jamás en claro/log.
        stored = False
        # [STEP 2·A3] ¿la conexión quedó COMPLETA? Si el flujo pidió acceso de larga duración
        # (offline_access / access_type=offline) pero el proveedor NO devolvió refresh_token, el
        # access_token muere a la ~1h sin poder renovarse → la conexión es PARCIAL, no "Conectado".
        rtok = res.get("refresh_token")
        partial = bool(oauth.wants_offline(cfg) and not rtok)
        if get_conn is not None:
            conn = get_conn()
            try:
                repo.upsert_key(conn, user_id=user_id, provider=name, secret=res["access_token"])
                # [TEST-FIX step-4.5 · T-8] Companion OAuth: el refresh_token (+ metadatos para
                # renovar sin re-consent) va CIFRADO Fernet bajo provider "<name>__oauth", igual que
                # cualquier secreto (upsert_key encripta). Sólo si el proveedor devolvió refresh_token
                # (Google lo hace con access_type=offline). El broker lo usa para renovar solo.
                if rtok:
                    import time as _t
                    # ⚠️ `expira_en` ABSOLUTO, no sólo el relativo. Persistir `expires_in`
                    # solo es el bug que otros ya pagaron: al releerlo no se sabe CUÁNDO
                    # empezó a contar, y un token muerto pasa por vivo. Se guarda el
                    # timestamp calculado; `expires_in`/`obtained_at` quedan por
                    # compatibilidad con los companions ya escritos.
                    _exp = res.get("expires_in")
                    _ahora_ts = _t.time()
                    companion = json.dumps({
                        "refresh_token": rtok,
                        "expires_in": _exp,
                        "obtained_at": _ahora_ts,
                        "expira_en": (_ahora_ts + float(_exp)) if _exp else None,
                        "token_url": cfg.get("token_url"),
                        "client_id_env": cfg.get("client_id_env"),
                        "client_secret_env": cfg.get("client_secret_env"),
                    })
                    repo.upsert_key(conn, user_id=user_id, provider=f"{name}__oauth", secret=companion)
                # [STEP 2·A3] Marcador de PARCIAL: cuando se pidió offline y no vino refresh, dejamos
                # una fila companion "<name>__oauth_partial" (metadata NO secreta) para que GET /keys
                # la exponga y la card pinte "Parcial" en vez de "Conectado" — la salud de la
                # credencial es VISIBLE, no un false-green que muere a la hora en medio de un run.
                # Si vino refresh (o no era offline), LIMPIAMOS cualquier marcador previo (re-conexión
                # exitosa tras una parcial).
                if partial:
                    # NOTA (best-effort): upsert_key/delete_key commitean por separado, así que el
                    # marker es una escritura NO atómica respecto del access_token. Si fallara ENTRE
                    # ambos commits, quedaría el access_token sin marker → se mostraría "Conectado"
                    # (false-green). Es baja probabilidad (misma conexión/txn local) y el peor caso
                    # se autocorrige al reconectar; si se vuelve crítico, envolver ambos en una sola txn.
                    import time as _t
                    marker = json.dumps({"partial": True, "reason": "no_refresh_token",
                                         "obtained_at": _t.time()})
                    repo.upsert_key(conn, user_id=user_id, provider=f"{name}__oauth_partial", secret=marker)
                else:
                    try:
                        repo.delete_key(conn, user_id=user_id, provider=f"{name}__oauth_partial")
                    except Exception:
                        pass
                stored = True
            finally:
                conn.close()
        if not stored:
            return _ret("oauth=error&reason=store")
        _used_states.add(state)
        ident = res.get("identity") or ""
        # PARCIAL → oauth=partial (la SPA lo distingue de ok); COMPLETO → oauth=ok.
        q = ("oauth=partial" if partial else "oauth=ok") + \
            (f"&id={urllib.parse.quote(str(ident))}" if ident else "")
        return _ret(q)

    return router


__all__ = ["build_connectors_router"]
