# CONTRATO AUTH / SESSION v2 — ❄️ CONGELADO

> **Estado: CONGELADO el 2026-07-20.** Sucede a `CONTRACT-AUTH-v1-FROZEN.md`, que queda
> como histórico y **sigue vigente para el camino Fernet** (CLI local, harnesses).
> Cambios incompatibles ⇒ v3 + migración, jamás edición silenciosa.

---

## 0. LA INVARIANTE MADRE — no cambió

> **Toda llamada `/v1` con identidad lleva una sesión → `user_id`. `user_id` scopea TODO.
> Nadie lee/escribe data de otro.**

Lo que cambió es **quién emite la sesión**, no cómo se autoriza. Y por eso el paso de v1
a v2 no tocó un solo endpoint: todo el backend autoriza LLAMANDO a `session_owner()`, no
reimplementando el parseo. Esa disciplina de v1 es lo que hizo que v2 costara poco.

## 1. LA COSTURA

```
repo.session_owner(token: Optional[str]) -> Optional[str]
```

**La firma es el contrato.** Acepta DOS formatos y devuelve siempre nuestro `users.id`:

| | v1 · Fernet | v2 · JWT de Supabase |
|---|---|---|
| Emisor | nosotros (`mint_session`) | Supabase Auth |
| Forma | token opaco base64 | JWT (`eyJ…`) |
| Caduca | **nunca** | sí (~1 h) + refresh |
| Verificación | descifrado local | firma **ES256 contra el JWKS** del proyecto |
| Usos vivos | CLI local, harnesses, sesiones legacy | usuarios finales |

**Orden: Fernet primero.** Es local y de microsegundos; el JWT puede implicar red. Probar
lo barato antes evita pagar red por cada request de un CLI que ni usa Supabase.

### El puente de identidad
`auth.users.id` (el `sub` del JWT) → `public.users.auth_uid` → `public.users.id`
(migración `0015`). **No se reescribió `users.id`**: acoplarlo al proveedor de identidad
de turno es el error que el §4-bis nos hizo evitar con los pagos. Una columna se cambia;
un id reescrito en quince tablas hay que volver a migrarlo.

El alta es **perezosa y RECLAMA**: si ya existe una cuenta con ese email, se le liga el
`auth_uid` en vez de crear una segunda — si no, quien se registró con password y después
entra por Google tendría dos cuentas y perdería sus agentes.

## 2. ⛔ LO QUE EL TOKEN NUNCA DICE

**El tier.** El token dice QUIÉN sos; el plan lo resuelve el servidor contra `users.tier`.
Si el tier viajara en el JWT, el cliente declararía su propio plan y **toda la muralla
premium se cae** — es literalmente el patrón que el Step 5 encontró y cerró cuatro veces
(ver `reports/step5/LECCION-identidad-del-cliente.md`).

Esta frontera es la razón de ser de la Opción A: **Supabase = identidad · nuestro
Postgres = tier.** No se negocia en v3 tampoco.

## 3. MÉTODOS DE ENTRADA — estado del launch

| Método | Estado | Por qué |
|---|---|---|
| **Google** | ✅ activo | no manda email; funciona sin dominio propio |
| **GitHub** | ✅ activo | ídem; y es el ICP (perfil dev) |
| Magic-link | ⛔ **desactivado** | requiere email fiable → requiere dominio propio |
| Email + password | ⛔ **desactivado** | el mail de confirmación tiene el mismo problema |

### Por qué se cayeron los dos de email (verificado, no supuesto)

El SMTP integrado de Supabase **sólo envía a direcciones del propio equipo** (*"Email
address not authorized"*) y a 2/hora — inservible para usuarios reales. Se conectó un
SMTP custom (Brevo) y **el correo llegó a funcionar** (`Sent` + `First opening` en el log).

Pero el remitente era `@hotmail.com`, y el SPF de Microsoft es `v=spf1
include:spf2.outlook.com -all`. Ese **`-all` es un rechazo duro**: ningún servidor de
Brevo está autorizado a enviar en nombre de hotmail.com. Resultado observado: entrega
errática, `Deferred` de Gmail (throttling por reputación) y spam.

Y para el magic-link el spam es peor que para un correo común: **el enlace caduca**. Si
el usuario lo encuentra a la tarde, ya no sirve, y la experiencia es "no puedo entrar"
sin explicación.

### 🔑 REQUISITO DOCUMENTADO PARA REACTIVARLOS

**Dominio propio verificado.** Con el dominio: se verifica en el proveedor de email, se
publican SPF y DKIM en el DNS, y el correo pasa a estar autenticado. Recién ahí
magic-link y email+password son fiables.

Estimado por persona usuaria: ~10 minutos de trabajo una vez que exista el dominio
(post-primera-venta). **Hasta entonces, esos dos métodos NO se muestran en la UI**: un
botón que falla es peor que un botón que no está.

## 4. EL LOCAL-FIRST — criterio no negociable de v2

El token de v1 no caducaba; el JWT sí, y refrescarlo **exige red**. Sin cuidado:

> se corta internet → pasa una hora → vence el token → no hay red para refrescar →
> **el cliente que pagó se queda afuera de su propio agente**

`platform/payments/session_cache.py` lo impide. Tres reglas:

1. **Nunca supimos quién sos** → anónimo. Fail-closed donde no lastima.
2. **Te conocimos y no hay red** → **seguís siendo vos**, marcado honesto. La caducidad
   de un JWT dice "hay que revalidar", NO "esta persona es un impostor".
3. **El servidor NIEGA (401 con red)** → afuera, en el acto.

**La distinción que lo sostiene: "no pude preguntar" ≠ "me dijeron que no".** El código
distingue `None` (silencio → preservar) de `False` (respuesta → cerrar). Confundirlas en
un sentido deja entrar a cualquiera; en el otro, echa al que pagó.

Esto **no es autoridad**: el servidor revalida siempre. Sostiene la experiencia local
(ver tus agentes, seguir trabajando offline), no los permisos.

## 5. VERIFICACIÓN

| Qué | Estado |
|---|---|
| Cache de sesión offline (el criterio duro) | ✅ **24/24** — 6 formas de fallo de red, ninguna deslogea |
| Rechazo de JWT contra el JWKS REAL | ✅ 16/16 — firma ajena, `alg:none`, vencido, emisor ajeno, kid desconocido |
| Fernet de v1 sigue resolviendo | ✅ la transición no rompió el camino viejo |
| Firma de `session_owner` intacta | ✅ 206 tests de phase1 sin modificar |
| **Caso POSITIVO del JWT** | ✅ **8/8 contra un token REAL de Supabase** |

### ✅ EL CASO POSITIVO — CERRADO (2026-07-20)

Se obtuvo un JWT **real** de Supabase (usuario de prueba, password grant) y se verificó
el camino completo, 8/8:

```
verificar() ACEPTA el token legítimo · extrae el sub correcto
session_owner() lo resuelve hasta NUESTRO users.id
el puente auth_uid queda escrito en la base
la cuenta nace FREE — el tier NO vino del token
un segundo uso NO duplica la cuenta
el MISMO token con un byte cambiado → rechazado
```

Los dos últimos son los que cierran el círculo:

- **"la cuenta nace free"** confirma en vivo la frontera de la Opción A: Supabase dice
  QUIÉN sos, nuestro Postgres decide QUÉ PLAN tenés. Un token no asciende a nadie.
- **"el mismo token, alterado, se rechaza"** descarta la hipótesis que hacía falta
  descartar: un verificador que acepta todo. Nueve rechazos + una aceptación + el mismo
  token roto rechazado = el verificador discrimina de verdad.

Nota de método: el usuario de prueba se confirmó por SQL
(`update auth.users set email_confirmed_at = now()`) porque el email de confirmación es
justo el que no llega sin dominio. La cuenta local se borró tras la prueba.
