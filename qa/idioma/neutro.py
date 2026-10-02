#!/usr/bin/env python3
"""neutro.py — voseo → español neutro, SÓLO en las líneas del censo (cadenas), con mapa determinista.
Uso: neutro.py <censo.tsv>... [--apply]   (sin --apply es dry-run: imprime antes/después)"""
import re, sys
from pathlib import Path

# ── imperativos -ar (vos -á → tú -a) se derivan; los -er/-ir y los irregulares van explícitos ──
IRREG = {
 "hacé":"haz","poné":"pon","tené":"ten","vení":"ven","decí":"di","salí":"sal","andá":"ve","sé":"sé",
 "leé":"lee","corré":"corre","volvé":"vuelve","respondé":"responde","devolvé":"devuelve","extraé":"extrae",
 "traé":"trae","prendé":"enciende","ofrecé":"ofrece","mantené":"mantén","concedé":"concede","componé":"compón",
 "proponé":"propón","aprendé":"aprende","entendé":"entiende","vendé":"vende","comé":"come","bebé":"bebe",
 "rompé":"rompe","creé":"cree","escondé":"esconde","mové":"mueve","recorré":"recorre","resolvé":"resuelve",
 "sostené":"sostén","obtené":"obtén","retené":"retén","contené":"contén","disponé":"dispón","exponé":"expón",
 "suponé":"supón","reconocé":"reconoce","agradecé":"agradece","establecé":"establece",
 # -ir (imperativo vos -í → tú)
 "seguí":"sigue","elegí":"elige","escribí":"escribe","abrí":"abre","repetí":"repite","corregí":"corrige",
 "definí":"define","describí":"describe","compartí":"comparte","incluí":"incluye","construí":"construye",
 "transcribí":"transcribe","resumí":"resume","imprimí":"imprime","medí":"mide","pedí":"pide","revertí":"revierte",
 "convertí":"convierte","subí":"sube","omití":"omite","emití":"emite","dividí":"divide","permití":"permite",
 "cumplí":"cumple","añadí":"añade","sustituí":"sustituye","descubrí":"descubre","conseguí":"consigue",
 "concluí":"concluye","distinguí":"distingue","exigí":"exige","insistí":"insiste","invertí":"invierte",
 "persistí":"persiste","admití":"admite","remití":"remite","discutí":"discute","introducí":"introduce",
 "reducí":"reduce","producí":"produce","conducí":"conduce","traducí":"traduce","recibí":"recibe","reuní":"reúne",
 "decidí":"decide","dormí":"duerme","moví":"mueve","volví":"vuelve","entendí":"entiende","aprendí":"aprende",
 # -ar con cambio de raíz o acento
 "mostrá":"muestra","contá":"cuenta","probá":"prueba","recordá":"recuerda","cerrá":"cierra","empezá":"empieza",
 "encontrá":"encuentra","recomendá":"recomienda","pensá":"piensa","comenzá":"comienza","acordá":"acuerda",
 "evaluá":"evalúa","continuá":"continúa","enviá":"envía","reenviá":"reenvía","variá":"varía","confiá":"confía",
 "situá":"sitúa","actuá":"actúa","atenuá":"atenúa","seteá":"configura","apretá":"presiona","arrancá":"empieza",
 "jalá":"trae","cableá":"cablea","dá":"da",
 # presente vos → tú
 "sos":"eres","tenés":"tienes","tenes":"tienes","podés":"puedes","podes":"puedes","querés":"quieres","queres":"quieres",
 "sabés":"sabes","hacés":"haces","decís":"dices","decis":"dices","venís":"vienes","ponés":"pones","conocés":"conoces",
 "entendés":"entiendes","debés":"debes","devolvés":"devuelves","recibís":"recibes","elegís":"eliges","volvés":"vuelves",
 "leés":"lees","imprimís":"imprimes","resolvés":"resuelves","preferís":"prefieres","pedís":"pides","medís":"mides",
 "escribís":"escribes","descubrís":"descubres","describís":"describes","convertís":"conviertes","aprendés":"aprendes",
 "abrís":"abres","seguís":"sigues","transcribís":"transcribes","querías":"querías","estés":"estés",
 "recordás":"recuerdas","acordás":"acuerdas","encontrás":"encuentras","mostrás":"muestras","contás":"cuentas",
 "probás":"pruebas","cerrás":"cierras","testeás":"pruebas","atenuás":"atenúas","evaluás":"evalúas","actuás":"actúas",
 # enclíticos
 "decime":"dime","contame":"cuéntame","pasame":"pásame","mandame":"mándame","mostrame":"muéstrame","avisame":"avísame",
 "escribime":"escríbeme","dejame":"déjame","preguntame":"pregúntame","pedime":"pídeme","haceme":"hazme","dame":"dame",
 "decile":"dile","contale":"cuéntale","mandale":"mándale","pasale":"pásale","mostrale":"muéstrale","sacale":"sácale",
 "agregale":"agrégale","sumale":"súmale","cambiale":"cámbiale","ponele":"ponle","dejale":"déjale",
 "fijate":"fíjate","acordate":"acuérdate","movete":"muévete","quedate":"quédate","animate":"anímate",
 "conectate":"conéctate","registrate":"regístrate","logueate":"inicia sesión","sumate":"súmate","anotate":"anótate",
 "asegurate":"asegúrate","olvidate":"olvídate","preparate":"prepárate","apurate":"apúrate","hacete":"hazte",
"pedilo":"pídelo","pedilos":"pídelos","decilo":"dilo","decila":"dila","reconectalo":"reconéctalo","sumale":"súmale","agregale":"agrégale",
 "cambiale":"cámbiale","armame":"ármame","generame":"genérame","redactame":"redáctame","resumime":"resúmeme","ajustale":"ajústale",
 "copiala":"cópiala","copialo":"cópialo","correlo":"córrelo","actualizalo":"actualízalo","cerralo":"ciérralo","seguila":"síguela",
 "computalos":"compútalos","listalo":"lístalo","declaralo":"decláralo","nombralo":"nómbralo","recalculalo":"recalcúlalo","compartime":"compárteme",
 "usalas":"úsalas","traeme":"tráeme","buscame":"búscame","describilo":"descríbelo","mandalos":"mándalos","guardalos":"guárdalos",
  "hacelo":"hazlo","hacela":"hazla","hacelos":"hazlos","ponelo":"ponlo","ponela":"ponla","ponelos":"ponlos",
 "sacalo":"sácalo","sacala":"sácala","mostralo":"muéstralo","mostrala":"muéstrala","guardalo":"guárdalo","guardala":"guárdala",
 "usalo":"úsalo","usala":"úsala","usalos":"úsalos","usalas":"úsalas","probalo":"pruébalo","probala":"pruébala",
 "tocalo":"tócalo","tocala":"tócala","abrilo":"ábrelo","abrila":"ábrela","elegilo":"elígelo","elegila":"elígela",
 "leelo":"léelo","leela":"léela","tenelo":"tenlo","pensalo":"piénsalo","revisalo":"revísalo","revisala":"revísala",
 "creelo":"créelo","dejalo":"déjalo","dejala":"déjala","cargalo":"cárgalo","cargala":"cárgala","mirala":"mírala",
 "miralo":"míralo","buscalo":"búscalo","buscala":"búscala","correlo":"córrelo","mandalo":"mándalo","pegala":"pégala",
 "pegalo":"pégalo","atajalo":"captúralo","encadenalas":"encadénalas","etiquetala":"etiquétala","acortala":"acórtala",
 "acortalo":"acórtalo","reformulalo":"reformúlalo","bajalo":"bájalo","arrancalo":"inícialo","quitala":"quítala",
 "quitalo":"quítalo","seguilo":"síguelo","seguila":"síguela","copialo":"cópialo","copiala":"cópiala",
 "configuralo":"configúralo","validalo":"valídalo","reintentalo":"reinténtalo","reemplazala":"reemplázala",
}
# palabras que terminan en -á/-é/-í/-ás/-és/-ís y NO son voseo
NOT = set("""está esté acá allá mamá papá quizá quizás ojalá sofá ya dé fe qué porqué café josé bebé puré así aquí ahí mí ti sí
allí más además atrás detrás jamás demás compás estás vas das después través interés inglés francés cortés estrés revés
país raíz maíz irá será hará dirá habrá podrá tendrá vendrá saldrá pondrá querrá sabrá cabrá valdrá verás tendrás podrás
harás serás dirás irás sabrás animate arnés caché comité mié haces sabes leí caí dale ché che vé""".split())
PREP_TI = {"por","de","para","a","sobre","en","sin","ante","contra","hacia","entre","según","desde","tras"}

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
def mapea(w):
    """w en minúsculas → reemplazo o None"""
    if w in NOT or es_futuro(w): return None
    if w in IRREG: return IRREG[w]
    if (w.endswith("rás") and es_futuro_ras(w)) or w.endswith("ré"): return None
    if w.endswith("á") and len(w)>2:           # imperativo -ar regular: mirá → mira
        base=w[:-1]
        if base.endswith(("gu","c","z")) and False: pass
        return base+"a"
    if w.endswith("ás") and len(w)>3:          # presente -ar: necesitás → necesitas
        return w[:-2]+"as"
    if w.endswith("és") and len(w)>3:          # presente -er: tenés → tienes (irregulares arriba)
        stem=w[:-2]
        if stem.endswith(("u","i","ie","io","o","é")): return None   # después, interés…
        return stem+"es"
    if w.endswith("ís") and len(w)>3:          # presente -ir: decís → dices (irregulares arriba)
        return w[:-2]+"es"
    return None

AMBIG_I = {k for k in IRREG if k.endswith("í") and k not in ("vení","salí","decí","dá")}  # 1ª pers. pretérito posible
PAST_PREV = re.compile(r"(?:\b(?:no|te|le|lo|la|me|les|los|las|se|ya|que|yo|nunca|jamás|todavía|recién|casi|tampoco|si|cuando|donde|como|porque)\s+|—\s*(?:no|te|lo|le)\s+)$", re.I)
IMP_PREV = re.compile(r"(?:^|[\s\"'`(\[]|[:;,.!?¡¿»«—·>\-]\s*|\b(?:y|o|e|u|luego|después|entonces|primero|ahora|siempre)\s+)$", re.I)

WORD = re.compile(r"(?<![A-Za-zÁÉÍÓÚÑáéíóúñ_])([A-Za-zÁÉÍÓÚÑáéíóúñ]{2,})(?![A-Za-zÁÉÍÓÚÑáéíóúñ_])")

def caso(orig, rep):
    if orig.isupper(): return rep.upper()
    if orig[0].isupper(): return rep[0].upper()+rep[1:]
    return rep

PAST_OVERRIDE={("product/app/design/cuarto/cuarto.pixi.html",5522),("product/app/design/cuarto/cuarto.pixi.html",6657),
("product/app/design/cuarto/cuarto.pixi.html",7639),("product/app/design/cuarto/cuarto.pixi.html",7761),("product/app/design/cuarto/cuarto.pixi.html",7797),
("product/app/design/cuarto/cuarto.pixi.html",8241),("product/app/design/cuarto/cuarto.pixi.html",8261),("product/app/design/cuarto/cuarto.pixi.html",8263),
("product/app/design/cuarto/cuarto.pixi.html",8377),("product/app/design/cuarto/cuarto.pixi.html",8383),("product/app/design/cuarto/cuarto.pixi.html",8384),
("product/app/design/cuarto/cuarto.pixi.html",8388),("product/app/design/i18n.js",552),("product/app/design/i18n.js",2475),("product/app/design/i18n.js",720),
("product/app/design/sala-v2/sala-v2.js",1097),("product/app/design/sala-v2/sala-v2.js",1101),("product/app/design/sala-v2/sala-v2.js",1118),
("product/backend/app/phase1/router.py",3206),("product/app/design/cuarto/cuarto.semaforo.js",172),("product/backend/app/phase1/centro_conexiones.py",453)}
_CUR=[None]
def convertir(line, flags):
    out=[]; last=0
    for m in WORD.finditer(line):
        w=m.group(1); wl=w.lower()
        rep=None
        if wl=="vos":
            if w.isupper() and len(line.strip())<6: rep=None
            else:
                prev=line[:m.start()].rstrip().split()
                pw=prev[-1].lower() if prev else ""
                pw=re.sub(r"^[^\wáéíóúñ]+","",pw)
                if pw=="con": rep="contigo"; 
                elif pw in PREP_TI: rep="ti"
                else: rep="tú"
                if rep=="contigo":
                    # reemplaza "con vos" entero
                    start=line.rfind(pw, 0, m.start())
                    out.append(line[last:start]); out.append(caso(line[start:start+3],"contigo")); last=m.end(); continue
        elif wl=="sos" and w.isupper():
            rep=None
        else:
            rep=mapea(wl)
            if rep and wl in AMBIG_I:
                if _CUR[0] in PAST_OVERRIDE: rep=None; flags.append(("pasado-override",w)); continue
                before=line[:m.start()]
                if PAST_PREV.search(before): rep=None; flags.append(("pasado",w))
                elif w[0].isupper() or IMP_PREV.search(before): pass
                else: rep=None; flags.append(("ambiguo",w))
        if rep is None: continue
        out.append(line[last:m.start()]); out.append(caso(w,rep)); last=m.end()
    out.append(line[last:])
    return "".join(out)

import tokenize, io
def spans_py(src):
    """línea -> [(col0,col1)] de tokens STRING"""
    out={}
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type==tokenize.STRING or tok.type==getattr(tokenize,"FSTRING_MIDDLE",-1):
                (l0,c0),(l1,c1)=tok.start,tok.end
                for ln in range(l0,l1+1):
                    a=c0 if ln==l0 else 0; b=c1 if ln==l1 else None
                    out.setdefault(ln,[]).append((a,b))
    except Exception: pass
    return out
def convertir_en(line, flags, spans):
    if spans is None:
        idx=line.rfind(" // ")
        if idx>0 and idx>max(line.rfind('"'),line.rfind("'"),line.rfind("`")):
            return convertir(line[:idx],flags)+line[idx:]
        return convertir(line,flags)
    out=[]; last=0
    for a,b in spans:
        out.append(line[last:a]); out.append(convertir(line[a:b] if b is not None else line[a:],flags)); last=b if b is not None else len(line)
    out.append(line[last:])
    r="".join(out)
    return r
def post(line):
    return line.replace("y inicia sesión","e inicia sesión").replace("Y inicia sesión","E inicia sesión")

def main():
    apply="--apply" in sys.argv
    tsvs=[a for a in sys.argv[1:] if a.endswith(".tsv")]
    targets={}
    for t in tsvs:
        for l in open(t):
            if l.startswith("#"): continue
            p=l.rstrip("\n").split("\t")
            if len(p)<5 or p[2]!="S": continue
            targets.setdefault(p[0],set()).add(int(p[1]))
    excl=[re.compile(x) for x in sys.argv[sys.argv.index("--excl")+1].split("|")] if "--excl" in sys.argv else []
    cambios=0; flags_all=[]
    for f,lns in sorted(targets.items()):
        if any(x.search(f) for x in excl): continue
        p=Path(f); src=p.read_text(encoding="utf-8"); lines=src.split("\n"); ch=False
        sp=spans_py(src) if p.suffix==".py" else None
        for ln in sorted(lns):
            if ln-1>=len(lines): continue
            old=lines[ln-1]; flags=[]; _CUR[0]=(f,ln)
            new=post(convertir_en(old,flags,(sp.get(ln) if sp is not None else None)))
            if sp is not None and ln not in sp: new=old
            for fl in flags: flags_all.append((f,ln,fl[0],fl[1]))
            if new!=old:
                cambios+=1; ch=True
                print(f"{f}:{ln}\n  - {old.strip()[:200]}\n  + {new.strip()[:200]}")
                lines[ln-1]=new
        if ch and apply: p.write_text("\n".join(lines),encoding="utf-8")
    print(f"# líneas cambiadas={cambios} {'APLICADO' if apply else 'DRY-RUN'}", file=sys.stderr)
    for fl in flags_all: print(f"# FLAG {fl[2]}: {fl[0]}:{fl[1]} «{fl[3]}»", file=sys.stderr)
main()
