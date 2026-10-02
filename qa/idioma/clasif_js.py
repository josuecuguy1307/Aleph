"""clasificador por caracteres para js/html: devuelve set de líneas que tienen texto FUERA de comentario"""
def lineas_codigo(src):
    out=set(); i=0; n=len(src); line=1; st=None  # st: None | "//" | "/*" | "<!--" | "'" | '"' | "`"
    while i<n:
        c=src[i]; nxt=src[i:i+4]
        if c=="\n":
            line+=1
            if st=="//": st=None
            i+=1; continue
        if st is None:
            if nxt.startswith("//"): st="//"; i+=2; continue
            if nxt.startswith("/*"): st="/*"; i+=2; continue
            if nxt.startswith("<!--"): st="<!--"; i+=4; continue
            if c in "'\"`": st=c; out.add(line); i+=1; continue
            if not c.isspace(): out.add(line)
            i+=1; continue
        if st=="//": i+=1; continue
        if st=="/*":
            if nxt.startswith("*/"): st=None; i+=2
            else: i+=1
            continue
        if st=="<!--":
            if nxt.startswith("-->"): st=None; i+=3
            else: i+=1
            continue
        # dentro de cadena
        if c=="\\": i+=2; continue
        if c==st: st=None; i+=1; continue
        out.add(line); i+=1
    return out
