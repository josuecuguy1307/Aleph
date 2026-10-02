"""idiomas.py — EL VOCABULARIO DE LAS GUARDAS, EN UN SOLO LUGAR.

Este archivo NO es del proyecto de origen: lo agrega Aleph.

QUÉ PROBLEMA CIERRA. `grounding.py` levanta sus murallas leyendo PROSA: doce `re.compile`
con vocabulario adentro que deciden si una guarda se arma. Estaban en inglés y chino. Aleph
corre en castellano, así que once de las doce **no se armaban nunca** — y eso no falla
ruidoso, falla del lado peligroso: la guarda no mira, y un número sin evidencia pasa.

Se midió una vez y se arregló UNA (`_PRICE_CONTEXT_RE`, con su comentario al lado). Un mes
después las otras once seguían sordas. Por eso el vocabulario deja de vivir dentro de cada
regex y pasa a estar acá: **agregar un idioma tiene que ser un archivo, no una cacería**.

CÓMO SE USA: cada constante de acá es un FRAGMENTO de alternancia —sin paréntesis, sin
anclas— pensado para pegarse con `|` adentro del `(?:…)` que ya existe. No reescribe los
patrones: los extiende. Así el comportamiento en inglés y chino queda intacto, byte por byte,
y lo único que cambia es que además oye castellano.

DOS REGLAS DE FORMA, aprendidas midiendo:
  · CON Y SIN TILDE. La prosa de un modelo no garantiza acentos: `precio`/`precío` no, pero
    `analisis`/`análisis` sí pasa todo el tiempo. Se escriben las dos formas o se usa una
    clase de caracteres.
  · RAÍCES, NO PALABRAS. `compr` cubre comprar, compré, comprando, compra. Una lista de
    conjugaciones envejece mal.

La vara que cuida que esto no se olvide vive del lado de la casa:
`qa/verify_guardas_por_idioma.py`.
"""

#: Pedido accionable de mercado: el usuario quiere operar, o quiere un precio para decidir.
#: Es la guarda que ARMA la resolución de identidad, así que sorda equivale a no tenerla.
ACCION_MERCADO_ES = (
    # EL VOSEO Y LAS TILDES NO SON UN DETALLE: la primera versión de esta línea no
    # matcheaba «comprá 10 acciones», que es como se escribe acá. Lo cazó la propia prueba.
    # Se enumeran las conjugaciones reales en vez de usar `compr\w*`, que se comería
    # «comprensión» y armaría la guarda por una palabra que no habla de mercado.
    r"\bcompr(?:a|á|as|ás|o|ó|é|e|en|ar|amos|aron|ando)\b|"
    r"\bvend(?:e|é|es|és|o|í|ió|en|er|emos|ieron|iendo)\b|"
    r"\bentrada\b|\bprecio objetivo\b|\bprecio actual\b|\b[úu]ltimo precio\b|"
    r"\bprecio de\b|\bcotizaci[óo]n\b|\bcotiza\b|\boperar\b|\bvaluaci[óo]n\b|"
    r"\bcu[áa]nto (?:vale|cuesta|est[áa])\b|"
    r"\b(?:cotiza|est[áa] listad[oa]|es p[úu]blica)\b"
)

#: Afirmación de que algo NO cotiza. Se vigila porque es la forma más común de alucinar
#: sobre una empresa que sí está listada.
PRIVADA_ES = (
    r"\bes (?:una )?(?:empresa )?(?:privada|no cotizante)\b|"
    r"\bno cotiza(?: en bolsa)?\b|\bsigue siendo privada\b|\bno est[áa] listada\b"
)

#: «Este número lo derivé», que es lo que habilita a mostrar una cuenta en vez de un dato.
DERIVACION_ES = r"\bderivad[oa]\b|\bcalculad[oa]\b|\bf[óo]rmula\b|\bbasad[oa] en\b|\bsurge de\b"

#: Un puntaje con etiqueta: confianza, probabilidad, tasa de acierto.
PUNTAJE_ES = r"confianza|convicci[óo]n|puntaje|calificaci[óo]n|probabilidad|tasa de acierto"

#: Montos agregados: lo que se afirma como total.
MONTO_ES = r"costo|total|monto|importe|capitalizaci[óo]n|valor de mercado|suma"

#: Unidades de cantidad que acompañan a un número en prosa financiera.
UNIDAD_ES = r"acciones?|t[íi]tulos?|contratos?|lotes?|veces|meses|semanas?|d[íi]as?"

#: Niveles prospectivos: «si supera», «objetivo», «stop». Son afirmaciones sobre el futuro
#: y por eso se separan de un precio observado.
NIVEL_ES = (
    r"\bmayor que\b|\bmenor que\b|\bpor encima de\b|\bpor debajo de\b|"
    r"\bnivel objetivo\b|\bprecio objetivo\b|\bstop\b|\bsoporte\b|\bresistencia\b|"
    r"\bsi (?:supera|rompe|cae)\b"
)

#: Las partes de una fecha escrita en prosa.
FECHA_ES = r"a[ñn]o|meses?|d[íi]as?"

#: Los rótulos de una vela: apertura, máximo, mínimo, cierre.
VELA_ES = r"apertura|m[áa]ximo|m[íi]nimo|cierre|fecha|d[íi]a de operaciones"

#: Conector de rango («de 10 a 12»), que en chino es 至.
RANGO_ES = r"\s*(?:a|hasta)\s*"

#: Cópula: «es», «fue», «queda en». El chino usa 为/是.
COPULA_ES = r"es|fue|queda en|resulta"
