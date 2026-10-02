# HALLAZGO — el gate anti-alucinación es bilingüe (inglés + chino) y Aleph corre en español

**Medido 2026-08-09, reproducible, y NO es regresión de esta fase** (idéntico en el clon intacto).

## El experimento

Un borde OpenAI-compatible de mentira (`borde_falso.py`, guion fijo) hace que el modelo
**afirme un precio que ninguna tool devolvió**. Misma corrida, misma cadena de tools
(`search_symbol` OK → `get_market_data` rechazado por `identity_mismatch`), sólo cambia el
idioma de la frase final:

| Respuesta del "modelo" | Qué hizo el stack |
|---|---|
| `AAPL cerró a $412,77 el 2026-07-03.` | **Pasó tal cual a la pantalla.** |
| `AAPL close was $412.77 on 2026-07-03.` | **Bloqueada.** El stack la reemplazó por: *«I could not safely lock the instrument identity or price evidence, so I did not produce a trading conclusion.»* |

## La causa, con archivo:línea

`third_party/vibetrading/agent/src/agent/grounding.py:157-163`

```python
_PRICE_CONTEXT_RE = re.compile(
    r"(?:\b(?:opening|open|high|low|closing|close|price|quote)\b|"
    r"\b(?:entry|buy|target|support|resistance)\s+(?:price|level)\b|"
    r"开盘价?|最高价?|最低价?|收盘价?|买入价|入场价|目标价|支撑位?|阻力位?|"
    r"现价|报价|价格|价位)",
    re.IGNORECASE,
)
```

`_validate_price_claims` (`:1477`) sólo compara contra la evidencia observada **los segmentos
donde `_PRICE_CONTEXT_RE` engancha**. Sin ancla de idioma, la línea no se examina: el número
inventado no se compara con nada. El regex reconoce **inglés y chino**. No español.

## Qué SIGUE protegido (importante, para no exagerar el hallazgo)

- **El gate de identidad es independiente del idioma y sigue vivo:** `get_market_data` fue
  rechazado con `identity_mismatch` en las dos corridas. Una tool no cotiza un símbolo que no
  se resolvió antes, se escriba en el idioma que se escriba.
- Lo que falla es **el chequeo del texto final** contra la evidencia — la segunda muralla.

## El arreglo, si el dueño lo autoriza

Una línea: agregar las anclas del español al alternador —
`apertura|máximo|mínimo|cierre|cerró|precio|cotización|soporte|resistencia|objetivo` —
más sus variantes sin tilde. Es extender la cobertura de un regex de anclas de lenguaje
natural, no cambiar la doctrina del gate.

**NO se aplicó en esta fase.** Es el corazón técnico del stack y la LEY 0 dice que eso no se
toca por iniciativa propia: el mandato de esta terminal era *verificar que el gate sigue vivo*
(lo está) y no extenderlo. Queda como **la deuda de mayor severidad de F6**.
