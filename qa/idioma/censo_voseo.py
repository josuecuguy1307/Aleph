#!/usr/bin/env python3
"""Censo de voseo: archivo:línea, separando CADENA de COMENTARIO."""
import re, sys, io, tokenize, json
from pathlib import Path

EXPL = r"""vos|sos|ché|che|tenés|tenes|podés|podes|querés|queres|sabés|sabes|hacés|haces|decís|decis|venís|ponés|conocés|entendés|debés|necesitás|
querías|tené|vení|andá|hacé|decí|poné|salí|subí|vé|
decime|contame|pasame|mandame|mostrame|avisame|escribime|dejame|preguntame|pedime|decile|contale|mandale|pasale|
fijate|acordate|movete|quedate|animate|conectate|registrate|logueate|sumate|anotate|asegurate|olvidate|preparate|acostumbrate|apurate|
hacelo|ponelo|sacalo|mostralo|guardalo|usalo|probalo|tocalo|abrilo|elegilo|leelo|tenelo|pensalo|revisalo|creelo|dejalo|cargalo|ponele|dale|
hacela|ponela|sacala|mostrala|guardala|usala|probala|tocala|abrila|elegila|leela|revisala|dejala|cargala|mirala|miralo|buscalo|buscala|
hacelos|ponelos|sacalos|mostralos|guardalos|usalos|probalos|abrilos|elegilos|leelos|revisalos|dejalos|cargalos|miralos|
elegí|escribí|abrí|seguí|pedí|repetí|subí|definí|describí|compartí|cumplí|permití|corregí|dividí|añadí|incluí|sustituí|
tuyo|tuya|tuyos|tuyas"""
EXPL = [w.strip() for w in EXPL.replace("\n","").split("|") if w.strip()]
# tuyo/tuya no es voseo — se saca; 'dale', 'che', 'ché', 'vé' son ruido en inglés/código → se revisan a mano
EXPL = [w for w in EXPL if w not in ("tuyo","tuya","tuyos","tuyas","dale","che","ché","vé")]
# imperativos vos con tilde (-á -é -í) e indicativos (-ás -és -ís)
GEN = r"[a-záéíóúñ]{2,}(?:á|ás|és|ís)|(?:pon|hac|le|corr|volv|respond|devolv|extra|tra|prend|ofrec|manten|conced|compon|aprend|entend|vend|com|beb|romp|cre|escond|mov|recorr|resolv|sosten|obten|reten|conten|propon|dispon|expon|supon|reconoc|agradec|establec|ten|ven|sub|abr|escrib|eleg|segu|dec|corrig|repet|defin|describ|compart|cumpl|permit|divid|añad|inclu|sustitu|ped|sal|ven|imprim|transcrib|resum|constru|convert|conclu|consegu|emit|descubr|revert|med|recib|reun|un|conclu|distingu|exig|insist|invert|persist|impr|omit|admit|remit|discut|introduc|reduc|produc|conduc|traduc)(?:é|í)"
PAT = re.compile(r"(?<![a-záéíóúñA-ZÁÉÍÓÚÑ_])(?:" + "|".join(EXPL) + r"|" + GEN + r")(?![a-záéíóúñA-ZÁÉÍÓÚÑ_])", re.I)

# exclusiones de la forma general (no son voseo)
NOT = set("""está esté ésta ésté acá allá mamá papá quizá quizás ojalá sofá bajá pashá agá ya dé sé fe qué porqué por-qué café josé bebé puré chalé
así aquí ahí mí ti tí sí allí alí rubí maní esquí bikini
más además atrás detrás jamás demás compás estás vas das quizás niñás verás tendrás podrás harás serás dirás irás sabrás estés dés vayás animate arnés caché persona usuaria comité mié haces sabes leí caí
después través interés inglés francés cortés estrés revés burgués marqués ciprés portugués holandés japonés chinés escocés irlandés finés
país raíz maíz anís chasís parís gris tenis
irá será hará dirá habrá podrá tendrá vendrá saldrá pondrá querrá sabrá cabrá valdrá
ana bebé pie""".split())
INF = re.compile(r".*(ará|erá|irá)$")
IMP_ARA={"prepar","repar","compar","separ","declar","dispar","ampar","par","aclar"}
IMP_ERA={"esper","gener","consider","recuper","oper","moder","numer","liber","toler","aceler","enumer","iter","alter","super","reiter","exager","deliber","coper","recuper"}
IMP_IRA={"mir","tir","gir","retir","admir","respir","inspir","aspir","expir","conspir"}
def es_futuro(w):
    w=w.lower()
    if len(w)<4: return False
    if w.endswith("ará"): return w[:-1] not in IMP_ARA and w[:-3] not in IMP_ARA
    if w.endswith("erá"): return w[:-1] not in IMP_ERA and w[:-3] not in IMP_ERA
    if w.endswith("irá"): return w[:-1] not in IMP_IRA and w[:-3] not in IMP_IRA
    return False
def es_futuro_ras(w):
    """-rás: futuro tú (infinitivo+ás) vs presente vos de un verbo en -rar (guardás, mirás)"""
    if w in ("verás","tendrás","podrás","harás","serás","dirás","irás","sabrás","habrás","vendrás","saldrás","pondrás","querrás","cabrás","valdrás"): return True
    if w.endswith("arás"): return w[:-2] not in IMP_ARA and w[:-4] not in IMP_ARA
    if w.endswith("erás"): return w[:-2] not in IMP_ERA and w[:-4] not in IMP_ERA
    if w.endswith("irás"): return w[:-2] not in IMP_IRA and w[:-4] not in IMP_IRA
    return False   # consonante + rás → presente vos (guardás, entrás, borrás)
def es_pret_1p(w):  # 1ª persona pretérito -é de -ar (probé, mandé) → ambiguo con imperativo -er (poné, hacé)
    return False

def matches(text):
    out=[]
    for m in PAT.finditer(text):
        w=m.group(0)
        wl=w.lower()
        if wl in NOT or es_futuro(wl): continue
        if (wl.endswith("rás") and es_futuro_ras(wl)) or (wl.endswith("ré") and wl not in ("corré","recorré")): continue
        if wl.endswith("és") and wl[:-2] and wl[:-2].endswith(("u","i","ie","io","o","é")): continue
        if wl.endswith(("ará","erá","irá")) and es_futuro(wl): continue
        # nombres propios / mayúscula inicial en medio de la frase seguidos de '.' → no
        out.append(w)
    return out

def _docstring_lines(src):
    import ast
    out=set()
    try: tree=ast.parse(src)
    except Exception: return out
    for node in ast.walk(tree):
        if isinstance(node,(ast.Module,ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef)):
            b=getattr(node,"body",None)
            if b and isinstance(b[0],ast.Expr) and isinstance(getattr(b[0],"value",None),ast.Constant) and isinstance(b[0].value.value,str):
                for ln in range(b[0].lineno, b[0].end_lineno+1): out.add(ln)
    return out

def clasificar_py(path, src):
    """devuelve dict línea -> 'S' (en cadena) | 'C' (comentario) | 'D' (docstring) por tokens"""
    kind={}
    ds=_docstring_lines(src)
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type==tokenize.COMMENT:
                for ln in range(tok.start[0], tok.end[0]+1): kind.setdefault(ln,set()).add("C")
            elif tok.type==tokenize.STRING:
                for ln in range(tok.start[0], tok.end[0]+1): kind.setdefault(ln,set()).add("D" if ln in ds else "S")
    except Exception as e:
        return None
    return kind

def clasificar_js(lines):
    kind={}
    inblock=False
    for i,l in enumerate(lines,1):
        s=l.strip()
        k=set()
        if inblock:
            k.add("C")
            if "*/" in s: inblock=False
        else:
            if s.startswith("//") or s.startswith("*") or s.startswith("/*") or s.startswith("<!--") or s.startswith("#"):
                k.add("C")
                if s.startswith("/*") and "*/" not in s: inblock=True
                if s.startswith("<!--") and "-->" not in s: inblock=True
            else:
                k.add("S")
                if "//" in s: k.add("C?")
        kind[i]=k
    return kind

def main(roots, exts):
    files=[]
    for r in roots:
        p=Path(r)
        if p.is_file(): files.append(p); continue
        for f in p.rglob("*"):
            if f.suffix in exts and f.is_file() and not any(x in f.parts for x in ("node_modules",".venv","dist","build",".next","target","__pycache__","lib")):
                files.append(f)
    res=[]
    for f in sorted(set(files)):
        try: src=f.read_text(encoding="utf-8")
        except Exception: continue
        lines=src.splitlines()
        if f.suffix==".py":
            kind=clasificar_py(f,src)
            if kind is None: kind=clasificar_js(lines)
        elif f.suffix in (".json",".md",".txt",".yaml",".yml"):
            kind={i:{"S"} for i in range(1,len(lines)+1)}
        else:
            kind=clasificar_js(lines)
        for i,l in enumerate(lines,1):
            ws=matches(l)
            if not ws: continue
            k=kind.get(i,set())
            tag="C" if k=={"C"} else ("S" if "S" in k else ("D" if "D" in k else "?"))
            res.append((str(f),i,tag,",".join(ws),l.strip()[:160]))
    return res

if __name__=="__main__":
    exts=set(sys.argv[1].split(","))
    roots=sys.argv[2:]
    res=main(roots,exts)
    for r in res: print("\t".join(map(str,r)))
    print(f"# total líneas={len(res)} cadena={sum(1 for r in res if r[2]=='S')} comentario={sum(1 for r in res if r[2]=='C')} docstring={sum(1 for r in res if r[2]=='D')}", file=sys.stderr)
