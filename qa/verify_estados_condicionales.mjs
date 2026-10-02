/* verify_estados_condicionales.mjs — la vara del BARRIDO DE ESTADOS CONDICIONALES.
 *
 * Por qué existe: un rediseño se rompe callado en lo que NO se ve al cargar. persona usuaria lo
 * detectó a ojo con la barra de "Disco y RAM" de Modelos —una sección que sólo aparece con
 * origen hf_local— que se había reestilado a ciegas. Esta vara hace eso a mano armada:
 * entra a cada pantalla, FUERZA todo estado oculto (hidden, display:none, popovers,
 * modales, drawers) y recién ahí mide.
 *
 * Así apareció lo más caro del barrido: el DRAWER de nav.js, invisible al cargar, aportaba
 * 4 bordes y 55 pesos fuera del sistema en CADA una de las 15 pantallas que lo cargan.
 *
 * DOS TRAMPAS DE MEDICIÓN, las dos aprendidas a los golpes acá:
 *
 *  1. Un borde TRANSPARENTE no es un borde. El sistema deja los tokens de línea en
 *     `transparent` en vez de borrarlos, para no romper las ~40 pantallas que los
 *     referencian. Contar por ANCHO daba 40 "bordes" en Home que no existían.
 *
 *  2. Comparar el texto contra los canales RGB del fondo IGNORANDO el alpha da falsos
 *     positivos a montones: un tinte de estado rgba(78,158,119,.14) con texto verde sólido
 *     tiene los mismos RGB pero se lee perfecto. Eran 90 falsos. Hay que COMPONER la pila
 *     de fondos hasta un color opaco y medir contraste real.
 *
 * Los ~6 pesos >400 que quedan de base NO son violación: son el wordmark "Aleph" en
 * Newsreader 600, que el sistema reserva explícitamente para la marca.
 *
 * Uso:  node qa/verify_estados_condicionales.mjs        (con el stack en :8340)
 */
import { chromium } from 'playwright';
const PANT = ['Home.dc.html','Modelos.dc.html','Historial.dc.html','Biblioteca.dc.html',
  // [Obra 4] el catálogo público dejó de ser una pantalla: es la SECCIÓN de Conectores, y
  // se abre con el mismo deep-link. `Conectar.dc.html` sin `?c=` ya sólo redirige, así que
  // censarla acá era censar un shim.
  'Settings.dc.html','Conectores.dc.html','Conectores.dc.html?catalogo=publico','Ayuda.dc.html',
  'Estados.dc.html','Auth.dc.html','Onboarding.dc.html','dispatch.dc.html','resolver.dc.html',
  'metodo/metodo.html','inspeccion/inspeccion.html','sala/sala.html','cuarto/cuarto.pixi.html'];
const b = await chromium.launch();
const filas = [];
for (const pag of PANT) {
  for (const tema of ['dark','light']) {
    const ctx = await b.newContext({viewport:{width:1400,height:900}});
    const p = await ctx.newPage(); const errs = [];
    p.on('pageerror', e => errs.push(String(e.message).slice(0,70)));
    try {
      await p.goto(`http://127.0.0.1:8340/${pag}${pag.includes('?')?'&':'?'}cb=${Date.now()}`,
        {waitUntil:'networkidle', timeout:45000});
    } catch(e) { filas.push({pag,tema,error:'no cargó'}); await ctx.close(); continue; }
    await p.waitForTimeout(pag.includes('pixi')?5000:3000);
    const antes = await p.evaluate(() => document.querySelectorAll('[hidden],[style*="display:none"],[style*="display: none"]').length);
    // FORZAR todo estado oculto
    await p.evaluate(() => {
      document.querySelectorAll('[hidden]').forEach(e=>{try{e.hidden=false}catch(_){}}); 
      document.querySelectorAll('*').forEach(e=>{
        try{ const cs=getComputedStyle(e);
          if(cs.display==='none' && e.tagName!=='SCRIPT' && e.tagName!=='STYLE') e.style.display='';
        }catch(_){}
      });
      document.querySelectorAll('[class*=pop],[class*=modal],[class*=overlay],[class*=drawer],[class*=panel],[id$=Overlay],[id$=Panel]')
        .forEach(e=>{try{e.classList.add('on','open','show')}catch(_){}});
    });
    await p.waitForTimeout(800);
    const m = await p.evaluate(() => {
      const cs = e => getComputedStyle(e);
      const vis = [...document.querySelectorAll('body *')].filter(e=>{
        const r=e.getBoundingClientRect();
        return r.width>2 && r.height>2 && cs(e).visibility!=='hidden' && cs(e).display!=='none';
      });
      // Comparar el texto contra los canales RGB del fondo IGNORANDO su alpha da falsos
      // positivos a montones: un tinte de estado rgba(78,158,119,.14) con texto verde sólido
      // es perfectamente legible, pero sus RGB son idénticos. Hay que COMPONER la pila de
      // fondos hasta llegar a un color opaco y recién ahí comparar.
      const parse = s => { const n=(s.match(/[\d.]+/g)||[]).map(Number);
        return n.length>=3 ? {r:n[0],g:n[1],b:n[2],a:n.length>3?n[3]:1} : null; };
      const sobre = (f, atras) => ({ r: f.r*f.a + atras.r*(1-f.a),
        g: f.g*f.a + atras.g*(1-f.a), b: f.b*f.a + atras.b*(1-f.a), a:1 });
      const fondoReal = el => {
        const capas=[]; let n=el;
        while(n && n!==document.documentElement){ const c=parse(cs(n).backgroundColor);
          if(c && c.a>0){ capas.push(c); if(c.a>=1) break; } n=n.parentElement; }
        let base = {r:255,g:255,b:255,a:1};
        const raiz = parse(cs(document.documentElement).backgroundColor);
        if (raiz && raiz.a>=1) base = raiz;
        for (let i=capas.length-1;i>=0;i--) base = sobre(capas[i], base);
        return base;
      };
      const lum = c => { const f=v=>{v/=255;return v<=.03928?v/12.92:Math.pow((v+.055)/1.055,2.4)};
        return .2126*f(c.r)+.7152*f(c.g)+.0722*f(c.b); };
      let invisibles = 0;
      vis.forEach(e=>{
        const t = e.textContent && e.textContent.trim();
        if(!t || t.length>200) return;
        if(e.children.length && !([...e.childNodes].some(n=>n.nodeType===3&&n.textContent.trim()))) return;
        const c = parse(cs(e).color); if(!c || c.a<0.1) return;
        const f = fondoReal(e);
        const L1=Math.max(lum(c),lum(f)), L2=Math.min(lum(c),lum(f));
        const contraste=(L1+.05)/(L2+.05);
        if (contraste < 1.6) invisibles++;   // ilegible de verdad, no "bajo AA"
      });
      return {
        nodos: vis.length,
        // un borde TRANSPARENTE no es un borde: el sistema los deja en `transparent` en vez
        // de borrarlos, para no romper las ~40 pantallas que los referencian.
        bordes: vis.filter(e=>{
          const op=c=>!/rgba\(.*,\s*0\)$/.test(c);
          return (parseFloat(cs(e).borderTopWidth)>0 && op(cs(e).borderTopColor))
              || (parseFloat(cs(e).borderLeftWidth)>0 && op(cs(e).borderLeftColor));
        }).length,
        insets: vis.filter(e=>/inset/.test(cs(e).boxShadow)).length,
        pesos: vis.filter(e=>parseInt(cs(e).fontWeight)>400).length,
        invisibles
      };
    });
    filas.push({pag, tema, ocultos_antes: antes, ...m, errores: errs.length});
    await ctx.close();
  }
}
await b.close();
console.log('PANTALLA'.padEnd(34)+'TEMA   OCULTOS  BORDES  INSETS  PESOS>400  INVISIBLES  ERR');
for (const f of filas) {
  if (f.error) { console.log(`${f.pag.padEnd(34)}${f.tema.padEnd(7)}${f.error}`); continue; }
  const alerta = (f.bordes||f.insets||f.pesos||f.invisibles||f.errores) ? '' : '  ok';
  console.log(`${f.pag.padEnd(34)}${f.tema.padEnd(7)}${String(f.ocultos_antes).padStart(6)}${String(f.bordes).padStart(8)}${String(f.insets).padStart(8)}${String(f.pesos).padStart(10)}${String(f.invisibles).padStart(12)}${String(f.errores).padStart(6)}${alerta}`);
}
