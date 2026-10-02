import re,sys,io,tokenize,ast
from pathlib import Path
SLANG=r"\b(gonna|wanna|gotta|y'all|ain't|kinda|sorta|dunno|lemme|gimme|folks|dude|buddy|cheers|heads[- ]up|no worries|awesome|yeah|yep|nope|hey|oops|whoops|stuff|a bunch|bunch of|kick off|hang on|hold on|pretty much|totally|literally|heck|damn|crap|bloody|mate|guys|cool|okay|ok,|nah|meh|whatever|super\s+\w+|tons of|lots of|a ton|no biggie|my bad|you bet|for sure|right away|in a sec|a sec\b|grab|nuke|zap|boom|yikes|dang|geez|jeez|sweet|neat|nifty|handy|dodgy|fancy|whilst|amongst|colour|favourite|organise|organisation|realise|behaviour|centre|licence|programme|catalogue|analyse|cancelled|grey|flavour|honour|labour|neighbour|apologise|recognise|customise|optimise|summarise|initialise|synchronise|authorise|prioritise|utilise|minimise|maximise|dialogue|travelling|modelling|labelled|signalling|fulfil|enrol|instalment|judgement|artefact|cheque|tyre|kerb|aluminium|maths|learnt|spelt|burnt|dreamt)\b"
CONTR=r"\b(don't|can't|won't|isn't|aren't|wasn't|weren't|doesn't|didn't|hasn't|haven't|hadn't|couldn't|wouldn't|shouldn't|it's|that's|there's|here's|what's|who's|where's|how's|let's|I'm|I've|I'll|I'd|you're|you've|you'll|you'd|we're|we've|we'll|we'd|they're|they've|they'll|they'd|he's|she's|it'll|that'll|there'll|ain't)\b"
PS=re.compile(SLANG,re.I); PC=re.compile(CONTR,re.I)
def docl(src):
    out=set()
    try: t=ast.parse(src)
    except Exception: return out
    for n in ast.walk(t):
        b=getattr(n,"body",None) if isinstance(n,(ast.Module,ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef)) else None
        if b and isinstance(b[0],ast.Expr) and isinstance(getattr(b[0],"value",None),ast.Constant) and isinstance(b[0].value.value,str):
            out.update(range(b[0].lineno,b[0].end_lineno+1))
    return out
def kinds(f,src,lines):
    if f.suffix==".py":
        ds=docl(src); k={}
        try:
            for tok in tokenize.generate_tokens(io.StringIO(src).readline):
                if tok.type==tokenize.COMMENT:
                    for ln in range(tok.start[0],tok.end[0]+1): k.setdefault(ln,set()).add("C")
                elif tok.type==tokenize.STRING:
                    for ln in range(tok.start[0],tok.end[0]+1): k.setdefault(ln,set()).add("D" if ln in ds else "S")
            return k
        except Exception: pass
    if f.suffix in (".json",".md",".txt"): return {i:{"S"} for i in range(1,len(lines)+1)}
    k={}; inb=False
    for i,l in enumerate(lines,1):
        s=l.strip()
        if inb:
            k[i]={"C"}; 
            if "*/" in s or "-->" in s: inb=False
        elif s.startswith(("//","*","/*","<!--","#")):
            k[i]={"C"}
            if (s.startswith("/*") and "*/" not in s) or (s.startswith("<!--") and "-->" not in s): inb=True
        else: k[i]={"S"}
    return k
roots=sys.argv[1:]
files=[]
for r in roots:
    p=Path(r)
    files+= [p] if p.is_file() else [f for f in p.rglob("*") if f.suffix in (".py",".js",".html",".json",".md",".txt") and f.is_file() and not any(x in f.parts for x in ("node_modules",".venv","dist","build",".next","target","__pycache__","lib","searxng","_exploraciones","vendor"))]
for f in sorted(set(files)):
    try: src=f.read_text(encoding="utf-8")
    except Exception: continue
    lines=src.splitlines(); k=kinds(f,src,lines)
    for i,l in enumerate(lines,1):
        s=PS.findall(l); c=PC.findall(l)
        if not s and not c: continue
        kk=k.get(i,set()); tag="C" if kk=={"C"} else ("S" if "S" in kk else ("D" if "D" in kk else "?"))
        print("\t".join([str(f),str(i),tag,("SLANG:"+",".join(s)) if s else "",("CONTR:"+",".join(c)) if c else "",l.strip()[:170]]))
