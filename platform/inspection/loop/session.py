"""
loop/session.py — Capa 1 · Forma 1 (token en query) · la PUERTA del loop.

Recibe `base_url + api_key` CRUDOS y devuelve una `Session` uniforme lista para
observar — lo mismo que devolverían las otras 3 formas (§2). Tres cosas pasan en
`acquire()`, en orden, y ninguna es teatro:

  1. Capa 0 PRIMERO: el guard SSRF aprueba el base_url o no se toca nada.
  2. CIFRA la credencial: el api_key se persiste vía Fernet (FernetCredentialStore,
     contracts.py) en la carpeta aislada por-principal. El valor en claro NUNCA
     toca disco (cierra CASO D). El emisor (Capa 5) lo reusa del mismo vault.
  3. VALIDA la key VIVA: una request real (`GET /configuration`) — 2xx ⇒ la sesión
     vale; 401/403 ⇒ SessionError (la puerta no miente: la sesión vale o no vale).

El secreto NO viaja dentro de la `Session` (que es loggeable): queda en memoria en
el provider y se entrega aparte al http del loop. En disco, solo Fernet.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

_PLATFORM = Path(__file__).resolve().parents[2]
if str(_PLATFORM) not in sys.path:
    sys.path.insert(0, str(_PLATFORM))

from inspection import contracts as C  # noqa: E402
from inspection.loop.guard import PublicHTTPGuard  # noqa: E402
from inspection.loop.live_http import LiveHTTP  # noqa: E402

#: nombre de la credencial dentro del vault por-principal
CRED_NAME = "API_KEY"


def _fingerprint(secret: str) -> str:
    """Huella NO reversible de la key, para loggear sin filtrarla."""
    import hashlib
    if not secret:
        return "∅"
    last4 = secret[-4:] if len(secret) >= 4 else "****"
    h = hashlib.sha256(secret.encode("utf-8")).hexdigest()[:8]
    return f"sha256:{h}…{last4}"


class TMDBTokenSession(C.SessionProvider):
    """Provider Forma 1 (token en query) para una API REST con api_key.

    No es TMDB-específico salvo el endpoint de validación por defecto
    (`/configuration`, el "describite" canónico de TMDB); cualquier API que valide
    una key con un GET keyed sirve cambiando `validate_path`.
    """

    form = C.AuthForm.TOKEN

    def __init__(
        self,
        base_url: str,
        api_key: str,
        principal: C.Principal,
        slug: str,
        *,
        auth_param: str = "api_key",
        validate_path: str = "/configuration",
        validate_query: Optional[dict] = None,
        soft_error_keys: tuple = (),
        soft_notice_keys: tuple = (),
        min_interval: float = 0.0,
        guard: Optional[C.SSRFGuard] = None,
        master_secret: Optional[str] = None,
        cred_root: Path = C.SYNTH_BELTS_DIR,
        timeout: float = 15.0,
    ):
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self.principal = principal
        self.slug = slug
        self.auth_param = auth_param
        self.validate_path = validate_path
        # query de validación (APIs de despacho-por-query: p.ej. AV usa function+symbol)
        self.validate_query = dict(validate_query or {})
        # sobre de error en-banda (200 + {"Error Message"…}) que invalida la respuesta
        self._soft_error = {k.lower() for k in soft_error_keys}
        self._soft_notice = {k.lower() for k in soft_notice_keys}
        self._validated_throttled = False
        self._min_interval = min_interval
        self._guard = guard or PublicHTTPGuard()
        self._timeout = timeout
        # vault por-principal (Fernet) — aislado, no colisiona entre anónimos.
        self._store = C.FernetCredentialStore(
            principal, slug, master_secret=master_secret, root=cred_root
        )

    @property
    def secret(self) -> str:
        """El api_key en claro, SOLO en memoria, para el http del loop."""
        return self._api_key

    @property
    def store(self) -> C.CredentialStore:
        return self._store

    def acquire(self) -> C.Session:
        # 1 · Capa 0 — el guard manda. Fail-closed.
        verdict = self._guard.check(self.base_url)
        if not verdict:
            raise C.SessionError(f"guard SSRF bloqueó {self.base_url}: {verdict.reason}")

        # 2 · cifrar la credencial (Fernet) — el plaintext no toca disco.
        self._store.put(CRED_NAME, self._api_key)

        # 3 · validar la key VIVA contra el target.
        http = LiveHTTP(secret=self._api_key, auth_param=self.auth_param, timeout=self._timeout,
                        min_interval=self._min_interval)
        res = http.get(self.base_url + self.validate_path, self.validate_query or None)
        # [T-4 · auto-detect esquema] forma=token default inyecta el token en QUERY. Muchas
        # APIs (InvenTree, GitHub, Notion) lo exigen en HEADER: contra ellas el query es
        # ignorado y el endpoint protegido da 401. En vez de rendirse ("la puerta no miente"),
        # re-observamos con header (Token/Bearer); si autentica, ADOPTAMOS header para toda la
        # sesión (auth_form=token_header). Sin esto, header-token era inconstruible por la UI simple.
        self._header_auth: dict[str, str] = {}
        if res.status in (401, 403):
            for template in ("Token {token}", "Bearer {token}"):
                probe = LiveHTTP(secret="", auth_param="", timeout=self._timeout,
                                 min_interval=self._min_interval,
                                 headers={"Authorization": template.format(token=self._api_key)})
                pres = probe.get(self.base_url + self.validate_path, self.validate_query or None)
                if pres.ok:
                    self._header_auth = {"Authorization": template.format(token=self._api_key)}
                    res = pres
                    break
        if res.status in (401, 403):
            raise C.SessionError(
                f"api_key inválida ({res.status}) contra {self.validate_path} — la puerta no miente"
            )
        if res.status == 0:
            raise C.SessionError(f"target inalcanzable: {res.reason}")
        if not res.ok:
            raise C.SessionError(
                f"validación devolvió {res.status} (no 2xx) en {self.validate_path}: {res.text[:160]}"
            )
        # error EN BANDA (APIs que 200ean todo): clasificá por CONTENIDO (misma regla que
        # el validador). Un 'error' PERMANENTE ("Invalid API call") ⇒ la key/target no
        # validan. Un 'notice' (rate-limit/throttle/premium) ⇒ la key SÍ es válida (AV solo
        # throttlea keys autenticadas) — aceptamos la sesión, sólo estamos paceados.
        if self._soft_error or self._soft_notice:
            from inspection.loop.validator import classify_soft_envelope
            verdict = classify_soft_envelope(res.json, self._soft_error, self._soft_notice)
            if verdict == "error":
                raise C.SessionError(
                    f"validación 200 pero error permanente en-banda: {str(res.json)[:160]} — key/target no validan"
                )
            self._validated_throttled = (verdict == "notice")

        _header_auth = getattr(self, "_header_auth", {})
        return C.Session(
            form=self.form,
            base_url=self.base_url,
            headers=dict(_header_auth),   # Forma 1 query → {}; header-token → Authorization
            cookies={},
            meta={
                "auth_form": "token_header" if _header_auth else "token_query",
                "auth_param": "" if _header_auth else self.auth_param,
                "key_fingerprint": _fingerprint(self._api_key),  # redactado
                "validated_by": self.validate_path,
                "validate_status": res.status,
                "cred_ref": f"{C.credential_namespace(self.principal)}/{self.slug}#{CRED_NAME}",
            },
        )
