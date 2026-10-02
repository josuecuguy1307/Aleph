Eres un analista cuantitativo (portfolio manager). Tu tarea: OPTIMIZAR una cartera para MAXIMIZAR el Sharpe ratio, iterando tú solo (backtest → leer Sharpe → reasignar pesos → re-backtest) hasta converger.

DATOS:
- Universo de activos: SPY (S&P 500), QQQ (Nasdaq 100), NVDA (Nvidia), TLT (bonos del Tesoro a largo plazo), GLD (oro).
- Cartera INICIAL: 60% NVDA, 40% QQQ (concentrada en tecnología). Pesos = [SPY 0, QQQ 0.40, NVDA 0.60, TLT 0, GLD 0].
- Objetivo: Sharpe ratio ≥ 1.2. Si el Sharpe está por debajo de 1.2, la cartera NO cumple.
- Herramienta: backtest_portfolio(tickers, weights, task_id, lookback_years, target_sharpe) corre un BACKTEST REAL con precios de Yahoo Finance y te devuelve el sharpe (anualizado), ann_return_pct, ann_vol_pct y max_drawdown_pct. Pasa SIEMPRE tickers=["SPY","QQQ","NVDA","TLT","GLD"] en ese orden, weights en el mismo orden, lookback_years=2, target_sharpe=1.2, y el MISMO task_id en cada iteración (así La Sala agrupa el loop como una sola convergencia).

PROCESO AUTÓNOMO (hazlo tú, NO preguntes, NO pares hasta cerrar):
1. Corre backtest_portfolio con la cartera actual (empieza con la inicial 60% NVDA / 40% QQQ).
2. Lee sharpe, ann_return_pct y ann_vol_pct del resultado y compara el sharpe con 1.2.
3. Si el Sharpe es bajo (< 1.2): el Sharpe = retorno / volatilidad. Una cartera concentrada en activos muy volátiles y MUY correlacionados entre sí (NVDA y QQQ se mueven casi igual) tiene una volatilidad enorme que castiga el Sharpe. Para SUBIR el Sharpe, DIVERSIFICA hacia activos poco o negativamente correlacionados con las acciones tecnológicas: los bonos (TLT) y el oro (GLD) bajan la volatilidad del portafolio MÁS de lo que bajan el retorno → el cociente retorno/vol sube. Reasigna peso desde NVDA/QQQ hacia SPY/TLT/GLD. Elige TÚ cuánto mover (más diversificación si la vol está muy alta), re-corre, y compara de nuevo. NO inventes el Sharpe: léelo de la herramienta en cada iteración.
4. Repite hasta que el Sharpe llegue a 1.2 o más (PASA) o llegues a 4 iteraciones.
5. Cierra con un veredicto: pesos finales, Sharpe final, retorno y volatilidad anualizados, max drawdown, PASA/FALLA, y cuántas iteraciones te tomó.

En cada paso explica brevemente QUÉ cambiaste y POR QUÉ (qué Sharpe y qué volatilidad viste, qué pesos moviste y con qué razonamiento). Cada backtest_portfolio con el mismo task_id se acumula solo como un paso de convergencia que La Sala muestra como una sola obra: el Sharpe subiendo (it.1 FALLA rojo → it.N PASA verde) y la curva de equity redibujándose a medida que la cartera mejora.
