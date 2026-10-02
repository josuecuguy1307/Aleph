# Capa de Safety (T9) — guards transversales de Aleph

> Capa **aditiva, fail-closed**: se monta encima de los seams del motor (recon, replay,
> run-executor) y solo puede **rechazar / frenar / pedir-humano**. No contiene lógica core.
> Todo stdlib. Estado bajo `product/backend/data/safety/`.

## Qué cubre (los 4 frentes de la directiva)

| Frente | Módulo | Qué hace |
|---|---|---|
| **1. SSRF/abuse en el recon** | `url_guard.py` + `rate_limit.py` | bloquea targets internos/metadata; allowlist de host; rate-limit por sujeto |
| **2. blast-radius en writes** | `kill_switch.py` + `audit_log.py` | freno de mano + auto-trip por volumen; bitácora encadenada |
| **3. gates legales por nicho** | `legal_gates.py` | ingeniería human-in-loop · finanzas descargo · medicina HIPAA dev-only |
| **4. privacidad** | `privacy.py` | retención por edad + "borrá mis datos" |

La fachada que los seams importan es `guards.py` (un import + una línea por seam).

---

## 1 · Anti-SSRF del recon (`url_guard.py`)

El recon navega/replica URLs que vienen del afuera. Sin guard, `http://169.254.169.254/`
(metadata de cloud), `http://127.0.0.1:6379/` (redis local) o `http://10.0.0.5/` (LAN)
convierten al motor en un proxy hacia la red interna. Defensa en capas, **fail-closed**:

1. **Esquema**: solo `http`/`https`. `file://`, `gopher://`, `data://`, `ftp://` → bloqueado.
2. **Sin credenciales embebidas** (`user:pass@host`) — vector de confusión.
3. **Rango de IP**: se **resuelve el host** (`getaddrinfo`) y se chequea **cada** dirección
   resultante. Si una sola no es `is_global` (privada / loopback / link-local / reserved /
   CGNAT / multicast / unspecified) → bloqueado. **Cierra el DNS-rebinding**: un nombre que
   resuelve a `127.0.0.1` cae igual que la IP literal.
4. **Metadata de cloud explícita** (`169.254.169.254`, `100.100.100.200`, `fd00:ec2::254`) —
   belt-and-suspenders sobre el filtro de rangos.
5. **Allowlist de host** opcional — `ALEPH_INSPECT_ALLOWLIST` ("solo software con derecho").

`allow_local_fixture=True` afloja **solo** loopback (para el target benigno local de la demo);
**nunca** afloja link-local/metadata/LAN, ni con el flag.

**Rate-limit** (`rate_limit.py`): ventana fija por sujeto (`user_id`, o `space_id` en su
defecto). Default 20 recon / hora — cada recon levanta un browser headless real.

## 2 · Blast-radius + kill-switch (`kill_switch.py`)

- **Kill-switch manual**: el operador traba un scope (`global` · `user:<id>` · `niche:<n>`) y
  todo write externo de ese scope se rechaza hasta el reset. **Persistido** (sobrevive a
  reinicios de `:8080`). El **reset** da borrón y cuenta nueva del contador de blast del scope.
- **Blast-radius automático**: cada write se cuenta por sujeto en una ventana. Si supera
  `ALEPH_WRITE_BLAST_MAX` (default 25 / 10 min), la capa **auto-traba** el kill-switch del
  usuario y bloquea — un agente en loop o un prompt-injection que dispara 1000 envíos **se
  frena solo**, sin esperar a un humano.

## 3 · Gates legales por nicho (`legal_gates.py`)

Capa **ortogonal** al approval-gate (que ya fuerza `money_touch`/`send` a `confirma-siempre`).
Lee `recipe.meta.nicho`:

- **Ingeniería** → `require_human=True`. Un cálculo/plano que sale sin que un profesional
  responsable lo apruebe es responsabilidad profesional (sellado/PE). _Requisito legal del campo._
- **Finanzas** → adjunta el descargo: **no es asesoría de inversión**; datos (SEC EDGAR/FRED)
  bajo sus términos de redistribución/atribución.
- **Medicina** → **HIPAA**: belt clínico (dicom/Orthanc) **solo dev/test** con datos sintéticos.
  En `ALEPH_ENV=prod` el run se **bloquea**; en dev/test se permite con banner no-PHI.

Solo **bloquea** o **exige-humano** o **anexa-aviso**. Nunca afloja. Agregar un nicho = una
entrada en `_POLICY`, sin tocar el core.

---

## Política de privacidad y retención (`privacy.py`)

**Clases de dato y retención por defecto** (override por env):

| Dato | Ubicación | Retención |
|---|---|---|
| Spaces de recon efímeros (`inspect-*`, `recon-*`, …) | `data/espacios/<id>/` | `ALEPH_RETENTION_SPACES_DAYS` = 30 d |
| Obra de runs (planillas/docs) | `data/run_outputs/<run_id>/` | `ALEPH_RETENTION_RUN_OUTPUTS_DAYS` = 90 d |
| Bitácora de seguridad | `data/safety/audit.jsonl` | `ALEPH_RETENTION_AUDIT_DAYS` = 365 d |
| Secretos BYOK/OAuth | vault (cifrado, Postgres `secrets`) | mientras exista la cuenta |

**"Borrá mis datos"** (`purge_user`): borra runs, spaces, artifacts y **secretos del vault**
del usuario. Mapea `user→recursos` por la DB (`runs.user_id`) si está viva; si no, opera sobre
los ids provistos y **reporta el alcance parcial honesto** (`complete:false`) — nunca finge un
borrado total. **Dry-run por default** (se mira el blanco antes de borrar); `--apply` ejecuta.

**Contención dura**: solo borra bajo `DATA_ROOT`, jamás sigue symlinks afuera, jamás borra la
raíz. Cada borrado deja una entrada en la bitácora (el **qué** se borró queda, aunque el dato
se vaya).

**Retención automática** (`retention_sweep`): borra artefactos efímeros más viejos que la
ventana. También dry-run por default.

---

## Runbook del operador (`cli.py`)

```bash
# estado general (kill-switches activos + integridad de la bitácora)
python platform/safety/cli.py status

# ¿esta URL es inspeccionable?
python platform/safety/cli.py check-url http://169.254.169.254/latest/meta-data/

# FRENO DE MANO ante incidente (agente en loop, exfiltración sospechada)
python platform/safety/cli.py kill global "incidente: agente en loop"
python platform/safety/cli.py kill user:0e890e35 "blast manual"
python platform/safety/cli.py reset global          # levanta el freno + limpia ventana

# cuántos writes/recon lleva un sujeto en la ventana
python platform/safety/cli.py blast 0e890e35

# bitácora (con verificación de cadena tamper-evident)
python platform/safety/cli.py audit 30

# "borrá mis datos" — dry-run y luego apply
python platform/safety/cli.py purge-user <user_id>
python platform/safety/cli.py purge-user <user_id> --apply

# barrido de retención
python platform/safety/cli.py retention            # dry-run
python platform/safety/cli.py retention --apply
```

## Config (env, todo override-able — `config.py`)

`ALEPH_INSPECT_ALLOWLIST` · `ALEPH_SAFETY_ALLOW_PRIVATE_TARGETS` (dev) ·
`ALEPH_RECON_RATE_MAX` / `_WINDOW_S` · `ALEPH_WRITE_BLAST_MAX` / `_WINDOW_S` ·
`ALEPH_RETENTION_*_DAYS` · `ALEPH_ENV` (dev|test|prod, gobierna los gates legales) ·
`ALEPH_DATA_ROOT`.

## Verificación

```bash
python platform/safety/tests_safety.py      # 17 tests, stdlib, sin red, sin mocks
python platform/safety/verify_done_bar.py   # demuestra las 3 BARRAS contra el entorno real
```
