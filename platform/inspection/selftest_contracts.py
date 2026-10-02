#!/usr/bin/env python3
"""
selftest_contracts.py — GATE VERDE de los CONTRATOS del motor de inspección.

Aserta el contrato, no el comportamiento (el motor todavía no existe). Cinco
candados, todos contra disco/runtime real (cero mocks):

  1. los tipos COMPILAN (import + construcción de cada dataclass/enum/Strategy).
  2. instanciar la ABC SessionProvider DIRECTO ⇒ falla (TypeError).
  3. un StubProvider que implementa la ABC pasa el test de interfaz (y los
     stubs de etapa satisfacen sus Protocols).
  4. COLISIÓN: dos anónimos distintos con el MISMO slug → NO colisionan. Se
     muestra que el PATH VIEJO (registry.belt_dir_for) SÍ colisiona y el NUEVO
     (contracts.credential_dir) no.
  5. CREDENCIAL: round-trip Fernet (cifra al guardar / descifra al leer) y el
     valor NUNCA queda en plaintext en disco.

Uso:
    PYTHONPATH=platform python platform/inspection/selftest_contracts.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_REPO_ROOT / "platform"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from inspection import contracts as C  # noqa: E402

_FAILS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    mark = "✓" if cond else "✗"
    print(f"  {mark} {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        _FAILS.append(name)


# ── stubs mínimos (la única "implementación" que existe: para probar la forma) ──
class StubProvider(C.SessionProvider):
    form = C.AuthForm.OPEN

    def acquire(self) -> C.Session:
        return C.Session(form=self.form, base_url="https://example.test")


class StubObserver:
    def observe(self, session, frontier):
        return C.Observation(capability_map={}, confirmed=(), passive=True)


class StubSynth:
    def synthesize(self, confirmed, observation, failed):
        return ()


class StubValidator:
    def validate(self, session, candidates):
        return C.Validation()


class StubEmitter:
    def emit(self, verified):
        return C.ForgedMCP(server_name="byo-x", belt_ref="data/x.mcp.json",
                           tools=(), cards=())


class StubGuard(C.SSRFGuard):
    def check(self, url: str) -> C.GuardVerdict:
        return C.GuardVerdict(allowed=True, reason="stub")


# ── 1 · LOS TIPOS COMPILAN ──────────────────────────────────────────────────────
def gate_types_compile() -> None:
    print("\n[1] los tipos compilan")
    cand = C.CandidateTool(name="get_thing", kind=C.ToolKind.READ,
                           endpoint="/api/v1/things", method="GET")
    ws = C.WorkingSet(
        confirmed=(C.Capability(endpoint="/api/v1/things", method="GET", evidence="200"),),
        candidates=(cand,),
        verified=(C.VerifiedTool(candidate=cand, verified_by="200-OK+schema-match"),),
        failed=(C.FailedTool(candidate=cand, failure=C.FailureClass.NOT_FOUND),),
        frontier=(C.FrontierLead(hint="id=42", kind="id"),),
    )
    ws2 = ws.with_(frontier=())
    strat = C.Strategy(discovery=C.Discovery.OPENAPI, auth=C.AuthChannel.HEADER,
                       tool_form=C.ToolForm.QUERY_PARAMS, navigation=C.Navigation.FOLLOW_LINKS)
    verdict = C.GuardVerdict(allowed=False, reason="loopback")

    check("WorkingSet inmutable (frozen)", _is_frozen(ws))
    check("with_ devuelve copia nueva sin mutar", ws2.frontier == () and ws.frontier != ())
    check("Strategy tiene los 4 niveles",
          all(hasattr(strat, a) for a in ("discovery", "auth", "tool_form", "navigation")))
    check("GuardVerdict.__bool__ == allowed", bool(verdict) is False)
    check("ToolKind READ/WRITE presentes",
          {C.ToolKind.READ, C.ToolKind.WRITE} == set(C.ToolKind))

    # §5 tabla de fallas: dos niveles + move + síntoma por cada fila
    syms = {"404", "400", "401_403", "200_schema", "all404_openapi", "timeout_5xx"}
    check("§5 cubre los 6 síntomas", {m.symptom for m in C.FailureClass} == syms)
    check("404 ⇒ REFINE_TOOL (interno)",
          C.FailureClass.from_symptom("404").level is C.FailureLevel.REFINE_TOOL)
    check("all404+openapi ⇒ SWITCH_STRATEGY (externo)",
          C.FailureClass.from_symptom("all404_openapi").level is C.FailureLevel.SWITCH_STRATEGY)
    check("timeout ⇒ SWITCH_STRATEGY (externo)",
          C.FailureClass.TIMEOUT.level is C.FailureLevel.SWITCH_STRATEGY)
    check("401/403 escala interno→externo (escalates)",
          C.FailureClass.FORBIDDEN.level is C.FailureLevel.REFINE_TOOL
          and C.FailureClass.FORBIDDEN.escalates is True)
    check("cada falla tiene un move", all(bool(m.move) for m in C.FailureClass))


def _is_frozen(obj) -> bool:
    try:
        obj.confirmed = ()  # frozen ⇒ FrozenInstanceError
        return False
    except Exception:
        return True


# ── 2 · LA ABC NO SE INSTANCIA DIRECTO ──────────────────────────────────────────
def gate_abc_not_instantiable() -> None:
    print("\n[2] instanciar la ABC SessionProvider directo ⇒ falla")
    try:
        C.SessionProvider()  # type: ignore[abstract]
        check("SessionProvider() abstracto levanta", False, "se instanció (MAL)")
    except TypeError as e:
        check("SessionProvider() abstracto levanta TypeError", True, str(e).split(" with ")[0])

    # SSRFGuard también es ABC
    try:
        C.SSRFGuard()  # type: ignore[abstract]
        check("SSRFGuard() abstracto levanta", False, "se instanció (MAL)")
    except TypeError:
        check("SSRFGuard() abstracto levanta TypeError", True)

    # CredentialStore también es ABC
    try:
        C.CredentialStore()  # type: ignore[abstract]
        check("CredentialStore() abstracto levanta", False, "se instanció (MAL)")
    except TypeError:
        check("CredentialStore() abstracto levanta TypeError", True)


# ── 3 · UN STUB QUE IMPLEMENTA LA ABC PASA LA INTERFAZ ──────────────────────────
def gate_stub_implements() -> None:
    print("\n[3] el stub que implementa la ABC pasa el test de interfaz")
    p = StubProvider()
    sess = p.acquire()
    check("StubProvider se instancia y acquire() devuelve Session",
          isinstance(sess, C.Session) and sess.form is C.AuthForm.OPEN)
    check("StubProvider ES un SessionProvider", isinstance(p, C.SessionProvider))
    check("StubGuard().check() devuelve GuardVerdict",
          isinstance(StubGuard().check("https://x.test"), C.GuardVerdict))

    # los stubs de etapa satisfacen sus Protocols (runtime_checkable)
    check("StubObserver satisface Observer", isinstance(StubObserver(), C.Observer))
    check("StubSynth satisface Synthesizer", isinstance(StubSynth(), C.Synthesizer))
    check("StubValidator satisface Validator", isinstance(StubValidator(), C.Validator))
    check("StubEmitter satisface Emitter", isinstance(StubEmitter(), C.Emitter))


# ── 4 · COLISIÓN DE NAMESPACE ANÓNIMO ───────────────────────────────────────────
def gate_anon_collision() -> None:
    print("\n[4] dos anónimos distintos, mismo slug ⇒ NO colisionan")
    slug = "byo-stripe"
    a = C.Principal(anon_id="sess-AAAA-1111")
    b = C.Principal(anon_id="sess-BBBB-2222")

    root = Path(tempfile.mkdtemp(prefix="contracts-ns-"))
    dir_a = C.credential_dir(a, slug, root=root)
    dir_b = C.credential_dir(b, slug, root=root)
    check("NUEVO: dos anon distintos ⇒ carpetas distintas", dir_a != dir_b,
          f"{dir_a.relative_to(root)}  vs  {dir_b.relative_to(root)}")
    check("NUEVO: ninguno usa el literal 'anon/<slug>' pelado",
          "anon/" + slug not in str(dir_a).replace(str(root), "").lstrip("/"))

    # demostrar que el PATH VIEJO sí colisionaba (usa la función real con el bug)
    try:
        from inspection import registry
        old_a = registry.belt_dir_for(None, slug)        # anon #1 (user_id None)
        old_b = registry.belt_dir_for("", slug)          # anon #2 (user_id "")
        check("VIEJO: registry.belt_dir_for colapsa ambos a 'anon/<slug>' (colisión)",
              old_a == old_b, str(old_a))
    except Exception as e:  # pragma: no cover — si registry no carga, lo replico inline
        old = lambda uid: root / (uid or "anon") / slug
        check("VIEJO (réplica): ambos anónimos ⇒ misma carpeta (colisión)",
              old(None) == old(""), f"({type(e).__name__} al importar registry)")

    # autenticados también disjuntos
    u1 = C.credential_dir(C.Principal(user_id="demo-user"), slug, root=root)
    u2 = C.credential_dir(C.Principal(user_id="otro"), slug, root=root)
    check("autenticados distintos ⇒ carpetas distintas", u1 != u2)

    # Principal vacío (el literal 'anon' compartido) está PROHIBIDO
    try:
        C.Principal()
        check("Principal() vacío levanta", False, "se construyó (MAL)")
    except ValueError:
        check("Principal() vacío (sin user_id ni anon_id) ⇒ ValueError", True)


# ── 5 · CREDENCIAL: ROUND-TRIP FERNET + NUNCA PLAINTEXT EN DISCO ────────────────
def gate_credential_fernet() -> None:
    print("\n[5] credencial: round-trip Fernet + cero plaintext en disco")
    secret_value = "sk_test_51RoundTripFernetNeverPlaintext_DEADBEEF42"
    root = Path(tempfile.mkdtemp(prefix="contracts-cred-"))
    principal = C.Principal(anon_id="sess-CRED-9999")
    store = C.FernetCredentialStore(principal, "byo-stripe",
                                    master_secret="selftest-master", root=root)

    check("antes de guardar: has() == False", store.has("STRIPE_API_KEY") is False)
    store.put("STRIPE_API_KEY", secret_value)
    check("después de guardar: has() == True", store.has("STRIPE_API_KEY") is True)
    got = store.get("STRIPE_API_KEY")
    check("round-trip: get() devuelve el valor original", got == secret_value)

    # re-abrir desde disco (otra instancia) ⇒ descifra igual
    store2 = C.FernetCredentialStore(principal, "byo-stripe",
                                     master_secret="selftest-master", root=root)
    check("persistencia: una instancia NUEVA descifra el mismo valor",
          store2.get("STRIPE_API_KEY") == secret_value)

    # el valor en claro NO aparece en NINGÚN archivo del árbol
    leaked = []
    for f in root.rglob("*"):
        if f.is_file():
            blob = f.read_bytes()
            if secret_value.encode("utf-8") in blob:
                leaked.append(str(f.relative_to(root)))
    check("NUNCA plaintext: el valor no aparece en ningún archivo en disco",
          not leaked, "limpio" if not leaked else f"FILTRADO en {leaked}")

    # secreto mal ⇒ no descifra (la cripto es real, no un passthrough)
    store3 = C.FernetCredentialStore(principal, "byo-stripe",
                                     master_secret="OTRO-master", root=root)
    check("clave maestra distinta ⇒ NO recupera el valor",
          store3.get("STRIPE_API_KEY") != secret_value)


def main() -> int:
    print("═" * 70)
    print("  GATE VERDE · contratos del motor de inspección")
    print("═" * 70)
    gate_types_compile()
    gate_abc_not_instantiable()
    gate_stub_implements()
    gate_anon_collision()
    gate_credential_fernet()
    print("\n" + "═" * 70)
    if _FAILS:
        print(f"  ROJO — {len(_FAILS)} check(s) fallaron: {_FAILS}")
        return 1
    print("  VERDE — todos los contratos asertados")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
