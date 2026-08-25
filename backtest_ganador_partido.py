"""
Backtest de un modelo de "probabilidad de ganar el partido" (no de ganar un
set), usando el historial completo de partidos terminados que el bot ya
tiene acumulado en `historico_partidos.json` (committeado en el repo,
congelado al 2026-08-19 -- de ahi en mas el workflow dejo de subirlo por el
limite de 100MB de GitHub, pero como dataset para calibrar un modelo la
frescura de los ultimos dias es irrelevante frente a tener ~337k partidos
reales).

Metodologia (resumen, ver informe generado para el detalle):

  1. Se carga el historico ya commiteado (`historico_partidos.json`, tal
     como lo deja `actions/checkout`). Si ademas hay credenciales de
     BetsAPI disponibles, se hace un "top-up" liviano (solo las paginas mas
     recientes de cada liga) para sumar los partidos jugados despues de esa
     foto congelada -- pero esto es un plus, no un requisito: el backtest
     funciona igual de bien solo con el archivo local.
  2. Se ordena todo cronologicamente y se simula un sistema de rating Elo
     PARTIDO A PARTIDO, en orden real de tiempo: para cada partido se
     registra primero el rating de cada jugador ANTES de jugarse ese
     partido (asi la prediccion nunca usa informacion del futuro), y recien
     despues se actualiza el rating con el resultado real.
  3. El Elo se elige como base del modelo (en vez de extender el enfoque de
     "probabilidad de ganar un set" que ya usa el bot) porque genera por
     construccion dos probabilidades que suman 100% entre los dos
     jugadores -- algo obligatorio si se van a mostrar los dos numeros
     juntos en la web, y que el enfoque actual (dos proporciones suavizadas
     independientes) no garantiza.
  4. Con esos snapshots "antes del partido" se separa el dataset
     cronologicamente en entrenamiento (80% mas antiguo) y validacion (20%
     mas reciente, nunca visto durante el ajuste). Se prueban varios
     valores de K de Elo, y para cada uno se ajusta por regresion logistica
     (a mano, con numpy, sin libreria de ML) el parametro que convierte la
     diferencia de rating en probabilidad. Se elige el K con mejor
     log-loss/Brier en el set de validacion.
  5. Se prueba ademas si sumarle un ajuste por historial cara a cara directo
     (mismo patron de "peso segun cuantos enfrentamientos hay" que ya usa
     el bot para otras señales) mejora la calibracion real en validacion; si
     no mejora, se descarta para no sumar complejidad de mas.
  6. Se informa Brier score, log-loss y una tabla de calibracion (igual
     formato que se uso para auditar la señal actual de "ambos ganan un
     set") sobre el 20% de validacion, nunca tocado durante el ajuste.

El resultado (backtest_ganador_partido_report.json / .md) es lo que decide
si este modelo esta listo para integrarse a la web, o si hace falta seguir
iterando antes de mostrarle esto a un usuario real.
"""

import json
import math
import os
import time

import numpy as np
import requests

ARCHIVO_HISTORICO_LOCAL = "historico_partidos.json"

BASE_URL = "https://api.b365api.com/v1"
TOKEN = os.environ.get("BETSAPI_TOKEN")
SPORT_ID_TENIS_MESA = 92

LIGAS = {
    "TT Elite Series": 29128,
    "Setka Cup": 22307,
    "Czech Liga Pro": 22742,
    "TT Cup": 29097,
}

# Top-up liviano: solo unas pocas paginas recientes por liga para sumar lo
# jugado despues de la foto congelada de historico_partidos.json. No es un
# backfill completo (eso ya esta hecho, ver commit history del archivo).
PAGINAS_TOPUP_POR_LIGA = 40

MIN_PARTIDOS_PREVIOS = 15  # mismo umbral que usa senales_reales.py hoy
RATING_INICIAL = 1500.0
VALORES_K_A_PROBAR = [10, 16, 20, 24, 32, 40]
FRACCION_ENTRENAMIENTO = 0.8

ARCHIVO_REPORTE_JSON = "backtest_ganador_partido_report.json"
ARCHIVO_REPORTE_MD = "backtest_ganador_partido_report.md"


# --------------------------------------------------------------------------
# 1. Carga del historico ya commiteado + top-up opcional
# --------------------------------------------------------------------------

def cargar_historico_local():
    if not os.path.exists(ARCHIVO_HISTORICO_LOCAL):
        print(f"AVISO: no encontre {ARCHIVO_HISTORICO_LOCAL} en el checkout, arranco vacio")
        return {}
    with open(ARCHIVO_HISTORICO_LOCAL, "r", encoding="utf-8") as f:
        historico = json.load(f)
    print(f"Cargados {len(historico)} partidos desde {ARCHIVO_HISTORICO_LOCAL} (foto congelada del repo)")
    return historico


def parsear_partido_api(evento):
    """Mismo esquema que produce parsear_partido() en senales_reales.py,
    para que los partidos de top-up sean compatibles con los ya cargados
    del archivo congelado."""
    home = evento.get("home", {}).get("name")
    away = evento.get("away", {}).get("name")
    ss = evento.get("ss")
    if not home or not away or not ss or "-" not in ss:
        return None
    try:
        sets_home, sets_away = (int(x) for x in ss.split("-"))
    except ValueError:
        return None
    if sets_home == sets_away:
        return None
    try:
        marca_tiempo = int(evento.get("time"))
    except (TypeError, ValueError):
        return None
    if sets_home > sets_away:
        ganador, perdedor = home, away
        sets_ganador, sets_perdedor = sets_home, sets_away
    else:
        ganador, perdedor = away, home
        sets_ganador, sets_perdedor = sets_away, sets_home
    return {
        "id": evento.get("id"),
        "jugador_a": home,
        "jugador_b": away,
        "ganador": ganador,
        "perdedor": perdedor,
        "sets_ganador": sets_ganador,
        "sets_perdedor": sets_perdedor,
        "time": marca_tiempo,
    }


def top_up_desde_api(historico):
    if not TOKEN:
        print("Sin BETSAPI_TOKEN configurado, salteo el top-up y uso solo el archivo local")
        return historico
    print(f"Top-up: pidiendo hasta {PAGINAS_TOPUP_POR_LIGA} paginas recientes por liga...")
    nuevos_totales = 0
    for nombre_liga, league_id in LIGAS.items():
        page = 1
        nuevos_liga = 0
        while page <= PAGINAS_TOPUP_POR_LIGA:
            try:
                resp = requests.get(
                    f"{BASE_URL}/events/ended",
                    params={"token": TOKEN, "sport_id": SPORT_ID_TENIS_MESA, "league_id": league_id, "page": page},
                    timeout=20,
                )
                data = resp.json()
            except (requests.exceptions.RequestException, ValueError) as exc:
                print(f"  {nombre_liga}: error en pagina {page} ({exc!r}), corto el top-up de esta liga")
                break
            resultados = data.get("results") if data.get("success") else None
            if not resultados:
                break
            todos_conocidos = True
            for ev in resultados:
                eid = str(ev.get("id"))
                if eid in historico:
                    continue
                todos_conocidos = False
                p = parsear_partido_api(ev)
                if p:
                    historico[eid] = p
                    nuevos_liga += 1
            if todos_conocidos:
                break
            time.sleep(0.2)
            page += 1
        print(f"  {nombre_liga}: {nuevos_liga} partidos nuevos via top-up")
        nuevos_totales += nuevos_liga
    print(f"Top-up total: {nuevos_totales} partidos nuevos")
    return historico


def normalizar_partido(p):
    """El archivo congelado y el top-up pueden traer llaves ligeramente
    distintas segun la version de parsear_partido que los genero; nos
    quedamos solo con lo que necesita la simulacion Elo."""
    if not p:
        return None
    jugador_a = p.get("jugador_a")
    jugador_b = p.get("jugador_b")
    ganador = p.get("ganador")
    t = p.get("time")
    if not jugador_a or not jugador_b or not ganador or t is None:
        return None
    if ganador not in (jugador_a, jugador_b):
        return None
    try:
        t = int(t)
    except (TypeError, ValueError):
        return None
    return {"jugador_a": jugador_a, "jugador_b": jugador_b, "ganador": ganador, "time": t}


# --------------------------------------------------------------------------
# 2. Simulacion Elo point-in-time + snapshots de H2H
# --------------------------------------------------------------------------

class EstadoJugador:
    __slots__ = ("rating", "n_partidos")

    def __init__(self):
        self.rating = RATING_INICIAL
        self.n_partidos = 0


def simular_elo_point_in_time(partidos_ordenados, k):
    """Devuelve una lista de snapshots, uno por partido elegible (ambos
    jugadores con >= MIN_PARTIDOS_PREVIOS partidos previos), con el rating
    de cada jugador tal como estaba INMEDIATAMENTE ANTES de ese partido, el
    historial H2H previo entre ese par exacto, y el resultado real."""
    estado = {}
    h2h = {}  # frozenset({a, b}) -> lista de (time, ganador)
    snapshots = []

    for p in partidos_ordenados:
        a, b, ganador = p["jugador_a"], p["jugador_b"], p["ganador"]
        ea = estado.setdefault(a, EstadoJugador())
        eb = estado.setdefault(b, EstadoJugador())

        par = frozenset((a, b))
        historial_par = h2h.get(par, [])

        if ea.n_partidos >= MIN_PARTIDOS_PREVIOS and eb.n_partidos >= MIN_PARTIDOS_PREVIOS:
            n_h2h_previo = len(historial_par)
            victorias_a_h2h = sum(1 for (_, g) in historial_par if g == a)
            snapshots.append({
                "time": p["time"],
                "jugador_a": a,
                "jugador_b": b,
                "rating_a": ea.rating,
                "rating_b": eb.rating,
                "n_h2h_previo": n_h2h_previo,
                "tasa_h2h_a": (victorias_a_h2h / n_h2h_previo) if n_h2h_previo else None,
                "gano_a": 1 if ganador == a else 0,
            })

        esperado_a = 1 / (1 + 10 ** ((eb.rating - ea.rating) / 400))
        resultado_a = 1.0 if ganador == a else 0.0
        ea.rating += k * (resultado_a - esperado_a)
        eb.rating += k * ((1 - resultado_a) - (1 - esperado_a))
        ea.n_partidos += 1
        eb.n_partidos += 1

        historial_par.append((p["time"], ganador))
        h2h[par] = historial_par

    return snapshots


# --------------------------------------------------------------------------
# 3. Regresion logistica simple (Newton-Raphson) sobre 1-2 variables
# --------------------------------------------------------------------------

def ajustar_logistica(X, y, iteraciones=50):
    n, p = X.shape
    Xb = np.hstack([np.ones((n, 1)), X])
    beta = np.zeros(Xb.shape[1])
    for _ in range(iteraciones):
        z = Xb @ beta
        pred = 1 / (1 + np.exp(-z))
        gradiente = Xb.T @ (y - pred)
        W = pred * (1 - pred)
        H = -(Xb.T * W) @ Xb - 1e-6 * np.eye(Xb.shape[1])
        try:
            paso = np.linalg.solve(H, gradiente)
        except np.linalg.LinAlgError:
            break
        beta = beta - paso
        if np.max(np.abs(paso)) < 1e-8:
            break
    return beta


def predecir_logistica(X, beta):
    n = X.shape[0]
    Xb = np.hstack([np.ones((n, 1)), X])
    z = Xb @ beta
    return 1 / (1 + np.exp(-z))


# --------------------------------------------------------------------------
# 4. Metricas de fiabilidad
# --------------------------------------------------------------------------

def brier_score(y_true, y_pred):
    return float(np.mean((y_pred - y_true) ** 2))


def log_loss(y_true, y_pred, eps=1e-12):
    y_pred = np.clip(y_pred, eps, 1 - eps)
    return float(-np.mean(y_true * np.log(y_pred) + (1 - y_true) * np.log(1 - y_pred)))


def tabla_calibracion(y_true, y_pred, n_bins=10):
    bins = np.linspace(0.5, 1.0, n_bins + 1)
    favorito_pred = np.where(y_pred >= 0.5, y_pred, 1 - y_pred)
    favorito_acierto = np.where(y_pred >= 0.5, y_true, 1 - y_true)

    filas = []
    for i in range(n_bins):
        lo, hi = bins[i], bins[i + 1]
        mask = (favorito_pred >= lo) & (favorito_pred < hi if i < n_bins - 1 else favorito_pred <= hi)
        n = int(mask.sum())
        if n == 0:
            continue
        filas.append({
            "rango": f"{lo:.2f}-{hi:.2f}",
            "n": n,
            "prediccion_promedio": float(favorito_pred[mask].mean()),
            "acierto_real": float(favorito_acierto[mask].mean()),
        })
    return filas


# --------------------------------------------------------------------------
# 5. Orquestacion
# --------------------------------------------------------------------------

def main():
    t0 = time.time()
    historico = cargar_historico_local()
    historico = top_up_desde_api(historico)

    partidos = [normalizar_partido(p) for p in historico.values()]
    partidos = [p for p in partidos if p]
    partidos.sort(key=lambda p: p["time"])
    print(f"\nTotal partidos usables tras normalizar: {len(partidos)}")
    if partidos:
        print(f"Rango de fechas (epoch): {partidos[0]['time']} a {partidos[-1]['time']}")
    print(f"Carga completa en {time.time() - t0:.0f}s\n")

    if len(partidos) < 5000:
        print("ADVERTENCIA: muy pocos partidos utilizables, el backtest no seria confiable. Abortando.")
        return

    resultados_por_k = {}
    mejor_k = None
    mejor_log_loss = math.inf
    mejor_snapshots = None
    mejor_beta_elo = None

    for k in VALORES_K_A_PROBAR:
        print(f"Simulando Elo point-in-time con K={k}...")
        snapshots = simular_elo_point_in_time(partidos, k)
        n = len(snapshots)
        if n < 1000:
            print(f"  K={k}: solo {n} snapshots elegibles, insuficiente, salto")
            continue

        corte = int(n * FRACCION_ENTRENAMIENTO)
        train, test = snapshots[:corte], snapshots[corte:]

        X_train = np.array([[s["rating_a"] - s["rating_b"]] for s in train])
        y_train = np.array([s["gano_a"] for s in train], dtype=float)
        X_test = np.array([[s["rating_a"] - s["rating_b"]] for s in test])
        y_test = np.array([s["gano_a"] for s in test], dtype=float)

        beta = ajustar_logistica(X_train, y_train)
        pred_test = predecir_logistica(X_test, beta)

        bs = brier_score(y_test, pred_test)
        ll = log_loss(y_test, pred_test)

        resultados_por_k[k] = {
            "n_train": len(train),
            "n_test": len(test),
            "beta": beta.tolist(),
            "brier_test": bs,
            "log_loss_test": ll,
        }
        print(f"  K={k}: n_train={len(train)} n_test={len(test)} brier={bs:.4f} log_loss={ll:.4f}")

        if ll < mejor_log_loss:
            mejor_log_loss = ll
            mejor_k = k
            mejor_snapshots = (train, test, X_train, y_train, X_test, y_test)
            mejor_beta_elo = beta

    if mejor_k is None:
        print("No se pudo ajustar ningun modelo (datos insuficientes). Abortando.")
        return

    print(f"\nMejor K de Elo segun log-loss en validacion: {mejor_k}")
    train, test, X_train, y_train, X_test, y_test = mejor_snapshots

    def features_con_h2h(subset):
        filas = []
        for s in subset:
            diff = s["rating_a"] - s["rating_b"]
            n_h2h = s["n_h2h_previo"]
            tasa_h2h = s["tasa_h2h_a"] if s["tasa_h2h_a"] is not None else 0.5
            peso_h2h = n_h2h / (n_h2h + 17)
            ajuste_h2h = peso_h2h * (tasa_h2h - 0.5)
            filas.append([diff, ajuste_h2h])
        return np.array(filas)

    X_train_h2h = features_con_h2h(train)
    X_test_h2h = features_con_h2h(test)
    beta_h2h = ajustar_logistica(X_train_h2h, y_train)
    pred_test_h2h = predecir_logistica(X_test_h2h, beta_h2h)
    bs_h2h = brier_score(y_test, pred_test_h2h)
    ll_h2h = log_loss(y_test, pred_test_h2h)

    pred_test_elo_solo = predecir_logistica(X_test, mejor_beta_elo)
    bs_elo_solo = brier_score(y_test, pred_test_elo_solo)
    ll_elo_solo = log_loss(y_test, pred_test_elo_solo)

    usar_h2h = ll_h2h < ll_elo_solo - 1e-4
    modelo_final = "elo_mas_h2h" if usar_h2h else "elo_solo"
    pred_test_final = pred_test_h2h if usar_h2h else pred_test_elo_solo
    beta_final = beta_h2h.tolist() if usar_h2h else mejor_beta_elo.tolist()

    baseline_pred = np.full_like(y_test, 0.5)
    baseline_bs = brier_score(y_test, baseline_pred)
    baseline_ll = log_loss(y_test, baseline_pred)

    calibracion = tabla_calibracion(y_test, pred_test_final)

    reporte = {
        "generado_epoch": int(time.time()),
        "total_partidos_historicos": len(partidos),
        "rango_fechas_epoch": [partidos[0]["time"], partidos[-1]["time"]] if partidos else None,
        "min_partidos_previos_para_elegibilidad": MIN_PARTIDOS_PREVIOS,
        "valores_k_probados": VALORES_K_A_PROBAR,
        "resultados_por_k": resultados_por_k,
        "mejor_k": mejor_k,
        "modelo_final": modelo_final,
        "beta_final": beta_final,
        "n_train": len(train),
        "n_test_holdout": len(test),
        "metricas_holdout": {
            "elo_solo": {"brier": bs_elo_solo, "log_loss": ll_elo_solo},
            "elo_mas_h2h": {"brier": bs_h2h, "log_loss": ll_h2h},
            "baseline_50_50": {"brier": baseline_bs, "log_loss": baseline_ll},
            "modelo_elegido": {
                "brier": bs_h2h if usar_h2h else bs_elo_solo,
                "log_loss": ll_h2h if usar_h2h else ll_elo_solo,
            },
        },
        "tabla_calibracion_holdout": calibracion,
    }

    with open(ARCHIVO_REPORTE_JSON, "w", encoding="utf-8") as f:
        json.dump(reporte, f, ensure_ascii=False, indent=2)

    md = []
    md.append("# Backtest: probabilidad de ganar el partido (Elo point-in-time)\n")
    md.append(f"- Partidos historicos usados: **{len(partidos)}**")
    md.append(f"- Snapshots elegibles (>= {MIN_PARTIDOS_PREVIOS} partidos previos por jugador): entrenamiento {len(train)}, validacion (holdout, nunca usado para ajustar) {len(test)}")
    md.append(f"- Mejor K de Elo probado: **{mejor_k}** (candidatos: {VALORES_K_A_PROBAR})")
    md.append(f"- Modelo final elegido: **{modelo_final}**" + (" (el ajuste por H2H SI mejoro la calibracion real)" if usar_h2h else " (el ajuste por H2H NO mejoro nada frente a Elo solo, se descarta por simplicidad)"))
    md.append("")
    md.append("## Metricas en el set de validacion (20% mas reciente, nunca visto al ajustar)\n")
    md.append("| Modelo | Brier score (menor = mejor) | Log-loss (menor = mejor) |")
    md.append("|---|---|---|")
    md.append(f"| Baseline ingenuo (siempre 50/50) | {baseline_bs:.4f} | {baseline_ll:.4f} |")
    md.append(f"| Elo solo | {bs_elo_solo:.4f} | {ll_elo_solo:.4f} |")
    md.append(f"| Elo + ajuste H2H | {bs_h2h:.4f} | {ll_h2h:.4f} |")
    md.append("")
    md.append("## Curva de calibracion del modelo elegido (holdout)\n")
    md.append("| Rango de probabilidad (del favorito) | n | Prediccion promedio | Acierto real |")
    md.append("|---|---|---|---|")
    for fila in calibracion:
        md.append(f"| {fila['rango']} | {fila['n']} | {fila['prediccion_promedio']*100:.1f}% | {fila['acierto_real']*100:.1f}% |")
    md.append("")

    with open(ARCHIVO_REPORTE_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(md))

    print("\nReporte guardado en:", ARCHIVO_REPORTE_JSON, "y", ARCHIVO_REPORTE_MD)
    print(f"\nTiempo total: {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
