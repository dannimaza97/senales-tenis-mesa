"""
Motor de senales de tenis de mesa con datos reales de BetsAPI.
Version con paquete completo: impulso, racha, % barridos, H2H detallado
y señales clave (1-1 al 2do, disputado al 3ro, termina 3-0, 4+ sets).
"""

import requests
import time
import datetime
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

MADRID_TZ = ZoneInfo("Europe/Madrid")

TOKEN = "263677-RrcfMZxfq5BJXV"
BASE_URL = "https://api.b365api.com/v1"
SPORT_ID_TENIS_MESA = 92

LIGAS = {
    "TT Elite Series": 29128,
    "Setka Cup": 22307,
    "Czech Liga Pro": 22742,
    "TT Cup": 29097,
}

TELEGRAM_TOKEN = "7754060707:AAFpXx9tCw1Zrksi544pQtfE6hskyPcAyao"
TELEGRAM_CHAT_IDS = ["663483538", "-1004364860113"]

TOP_N = 40


def enviar_telegram(texto):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    trozos = [texto[i:i+3800] for i in range(0, len(texto), 3800)] or [texto]
    for chat_id in TELEGRAM_CHAT_IDS:
        for trozo in trozos:
            try:
                requests.post(url, data={"chat_id": chat_id, "text": trozo}, timeout=15)
            except Exception as e:
                print(f"Error enviando a Telegram (chat {chat_id}): {e}")


def limpiar_archivos_antiguos(dias=7):
    import glob
    import os
    ahora = time.time()
    limite = dias * 24 * 60 * 60
    for ruta in glob.glob("senales_*.txt"):
        try:
            edad = ahora - os.path.getmtime(ruta)
            if edad > limite:
                os.remove(ruta)
                print(f"Borrado archivo antiguo: {ruta}")
        except Exception:
            pass


ARCHIVO_HISTORICO = "historico_partidos.json"


def cargar_historico():
    import json
    import os
    if not os.path.exists(ARCHIVO_HISTORICO):
        return {}
    try:
        with open(ARCHIVO_HISTORICO, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def guardar_historico(historico):
    import json
    with open(ARCHIVO_HISTORICO, "w", encoding="utf-8") as f:
        json.dump(historico, f, ensure_ascii=False)


ARCHIVO_PENDIENTES = "predicciones_pendientes.json"


def cargar_pendientes():
    import json
    import os
    if not os.path.exists(ARCHIVO_PENDIENTES):
        return {}
    try:
        with open(ARCHIVO_PENDIENTES, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def guardar_pendientes(pendientes):
    import json
    with open(ARCHIVO_PENDIENTES, "w", encoding="utf-8") as f:
        json.dump(pendientes, f, ensure_ascii=False, indent=2)


def obtener_resultado_partido(event_id):
    try:
        resp = requests.get(f"{BASE_URL}/event/view", params={"token": TOKEN, "event_id": event_id}, timeout=15)
    except requests.exceptions.RequestException:
        return None
    try:
        data = resp.json()
    except ValueError:
        return None
    if not data.get("success") or not data.get("results"):
        return None
    return data["results"][0]


ARCHIVO_RESULTADOS_NOTIFICADOS = "resultados_notificados.json"


def cargar_resultados_notificados():
    import json
    import os
    if not os.path.exists(ARCHIVO_RESULTADOS_NOTIFICADOS):
        return {}
    try:
        with open(ARCHIVO_RESULTADOS_NOTIFICADOS, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def guardar_resultados_notificados(datos):
    import json
    with open(ARCHIVO_RESULTADOS_NOTIFICADOS, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False)


ARCHIVO_ESTADISTICAS = "estadisticas.json"


def cargar_estadisticas():
    import json
    import os
    hoy = datetime.date.today().isoformat()
    if not os.path.exists(ARCHIVO_ESTADISTICAS):
        return {"fecha": hoy, "ganadoras": 0, "perdidas": 0}
    try:
        with open(ARCHIVO_ESTADISTICAS, "r", encoding="utf-8") as f:
            datos = json.load(f)
        if datos.get("fecha") != hoy:
            return {"fecha": hoy, "ganadoras": 0, "perdidas": 0}
        return datos
    except Exception:
        return {"fecha": hoy, "ganadoras": 0, "perdidas": 0}


def guardar_estadisticas(datos):
    import json
    with open(ARCHIVO_ESTADISTICAS, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False)


def comprobar_predicciones_anteriores():
    pendientes = cargar_pendientes()
    if not pendientes:
        return
    notificados = cargar_resultados_notificados()
    estadisticas = cargar_estadisticas()
    aun_pendientes = {}
    for event_id, pred in pendientes.items():
        if event_id in notificados:
            continue
        detalle = obtener_resultado_partido(event_id)
        if detalle is None:
            aun_pendientes[event_id] = pred
            continue
        if str(detalle.get("time_status")) != "3":
            aun_pendientes[event_id] = pred
            continue
        resultado = parsear_partido(detalle)
        if resultado is None:
            continue
        acerto = resultado["sets_perdedor"] >= 1
        if acerto:
            estadisticas["ganadoras"] += 1
            mensaje = (
                f"GANADORA ✅\n"
                f"{pred['liga'].upper()}: {pred['home'].upper()} VS {pred['away'].upper()}\n"
                f"AMBOS JUGADORES GANARON AL MENOS UN SET\n"
                f"📊 Hoy: {estadisticas['ganadoras']} verdes / {estadisticas['perdidas']} rojas"
            )
            enviar_telegram(mensaje)
        else:
            estadisticas["perdidas"] += 1
            mensaje = (
                f"PERDIDA ❌😢\n"
                f"{pred['liga'].upper()}: {pred['home'].upper()} VS {pred['away'].upper()}\n"
                f"TERMINO {resultado['sets_ganador']}-{resultado['sets_perdedor']} (BARRIDA)\n"
                f"📊 Hoy: {estadisticas['ganadoras']} verdes / {estadisticas['perdidas']} rojas"
            )
            enviar_telegram(mensaje)
        notificados[event_id] = True
    guardar_pendientes(aun_pendientes)
    guardar_resultados_notificados(notificados)
    guardar_estadisticas(estadisticas)


def obtener_partidos_finalizados(league_id, paginas=3):
    partidos = []
    for page in range(1, paginas + 1):
        try:
            resp = requests.get(f"{BASE_URL}/events/ended", params={
                "token": TOKEN, "sport_id": SPORT_ID_TENIS_MESA,
                "league_id": league_id, "page": page,
            }, timeout=15)
        except requests.exceptions.RequestException:
            print("  (aviso: tiempo de espera agotado, saltando esta pagina)")
            break
        try:
            data = resp.json()
        except ValueError:
            print("  (aviso: respuesta no valida de la API, esperando y continuando)")
            time.sleep(3)
            break
        if not data.get("success") or not data.get("results"):
            break
        partidos.extend(data["results"])
        time.sleep(0.5)
    return partidos


def obtener_partidos_proximos(league_id, paginas=3):
    partidos = []
    for page in range(1, paginas + 1):
        try:
            resp = requests.get(f"{BASE_URL}/events/upcoming", params={
                "token": TOKEN, "sport_id": SPORT_ID_TENIS_MESA,
                "league_id": league_id, "page": page,
            }, timeout=15)
        except requests.exceptions.RequestException:
            print("  (aviso: tiempo de espera agotado buscando proximos, saltando)")
            break
        try:
            data = resp.json()
        except ValueError:
            break
        if not data.get("success") or not data.get("results"):
            break
        partidos.extend(data["results"])
        time.sleep(0.3)
    return partidos


def parsear_partido(evento):
    home = evento.get("home", {}).get("name")
    away = evento.get("away", {}).get("name")
    ss = evento.get("ss")
    if not ss or "-" not in ss:
        return None
    try:
        sets_home, sets_away = (int(x) for x in ss.split("-"))
    except ValueError:
        return None

    sets_detalle = []
    scores = evento.get("scores") or {}
    for i in range(1, 8):
        clave = str(i)
        if clave not in scores:
            break
        try:
            ph = int(scores[clave].get("home"))
            pa = int(scores[clave].get("away"))
            sets_detalle.append((ph, pa))
        except (TypeError, ValueError):
            break

    if sets_home > sets_away:
        ganador, perdedor = home, away
        sets_ganador, sets_perdedor = sets_home, sets_away
    else:
        ganador, perdedor = away, home
        sets_ganador, sets_perdedor = sets_away, sets_home

    try:
        marca_tiempo = int(evento.get("time"))
    except (TypeError, ValueError):
        marca_tiempo = 0

    return {
        "id": evento.get("id"),
        "jugador_a": home, "jugador_b": away,
        "ganador": ganador, "perdedor": perdedor,
        "sets_ganador": sets_ganador, "sets_perdedor": sets_perdedor,
        "sets": sets_detalle,
        "time": marca_tiempo,
    }


@dataclass
class Jugador:
    nombre: str
    rating: float = 50.0
    historial_rating: list = field(default_factory=lambda: [50.0])


def actualizar_elo(jugadores, partidos, k=20):
    for p in partidos:
        a = jugadores.setdefault(p["jugador_a"], Jugador(p["jugador_a"]))
        b = jugadores.setdefault(p["jugador_b"], Jugador(p["jugador_b"]))
        esperado_a = 1 / (1 + 10 ** ((b.rating - a.rating) / 400))
        resultado_a = 1.0 if p["ganador"] == a.nombre else 0.0
        a.rating += k * (resultado_a - esperado_a)
        b.rating += k * ((1 - resultado_a) - (1 - esperado_a))
        a.historial_rating.append(a.rating)
        b.historial_rating.append(b.rating)


def prop_suavizada(eventos, n, alpha=1.5):
    return (eventos + alpha) / (n + 2 * alpha)


def peso_h2h(n, c=17):
    return n / (n + c)


def partidos_de_jugador(jugador, partidos):
    juegos = [p for p in partidos if jugador in (p["jugador_a"], p["jugador_b"])]
    juegos.sort(key=lambda p: p["time"])
    return juegos


def prob_jugador_gana_set(jugador, oponente, partidos):
    juegos = partidos_de_jugador(jugador, partidos)
    n = len(juegos)
    eventos = sum(1 for p in juegos if not (p["perdedor"] == jugador and p["sets_perdedor"] == 0))
    base = prop_suavizada(eventos, n)

    enfrentamientos = [p for p in partidos if {p["jugador_a"], p["jugador_b"]} == {jugador, oponente}]
    nh = len(enfrentamientos)
    if nh == 0:
        return base, nh
    eventos_h2h = sum(1 for p in enfrentamientos if not (p["perdedor"] == jugador and p["sets_perdedor"] == 0))
    p_h2h = prop_suavizada(eventos_h2h, nh)
    w = peso_h2h(nh)
    return w * p_h2h + (1 - w) * base, nh


def prob_ambos_ganan_set(nombre_a, nombre_b, partidos):
    return prob_patron(nombre_a, nombre_b, partidos, lambda p: p["sets_perdedor"] >= 1)


def prob_patron(nombre_a, nombre_b, partidos, funcion_patron):
    jugados_a = partidos_de_jugador(nombre_a, partidos)
    jugados_b = partidos_de_jugador(nombre_b, partidos)
    base_a = prop_suavizada(sum(1 for p in jugados_a if funcion_patron(p)), len(jugados_a))
    base_b = prop_suavizada(sum(1 for p in jugados_b if funcion_patron(p)), len(jugados_b))
    base = (base_a + base_b) / 2
    enfrentamientos = [p for p in partidos if {p["jugador_a"], p["jugador_b"]} == {nombre_a, nombre_b}]
    n = len(enfrentamientos)
    if n == 0:
        return base, n
    eventos_h2h = sum(1 for p in enfrentamientos if funcion_patron(p))
    p_h2h = prop_suavizada(eventos_h2h, n)
    w = peso_h2h(n)
    return w * p_h2h + (1 - w) * base, n


def resultado_set(pts_a, pts_b):
    return "a" if pts_a > pts_b else "b"


def patron_1_1_al_2do_set(p):
    if len(p["sets"]) < 2:
        return False
    return resultado_set(*p["sets"][0]) != resultado_set(*p["sets"][1])


def patron_disputado_3er_set(p):
    return len(p["sets"]) >= 3


def patron_termina_3_0(p):
    return p["sets_perdedor"] == 0


def patron_4_mas_sets(p):
    return len(p["sets"]) >= 4


def color_semaforo(p):
    if p >= 0.75:
        return "VERDE"
    if p >= 0.70:
        return "AMARILLO"
    return None


def calcular_impulso(jugador, partidos, n_reciente=10):
    juegos = partidos_de_jugador(jugador, partidos)
    if not juegos:
        return 0.0
    tasa_global = sum(1 for p in juegos if p["ganador"] == jugador) / len(juegos)
    recientes = juegos[-n_reciente:]
    tasa_reciente = sum(1 for p in recientes if p["ganador"] == jugador) / len(recientes)
    return tasa_reciente - tasa_global


def calcular_racha(jugador, partidos):
    juegos = partidos_de_jugador(jugador, partidos)
    racha = 0
    for p in reversed(juegos):
        gano = p["ganador"] == jugador
        if racha == 0:
            racha = 1 if gano else -1
        elif (racha > 0 and gano) or (racha < 0 and not gano):
            racha += 1 if gano else -1
        else:
            break
    return racha


def calcular_tasa_victorias(jugador, partidos):
    juegos = partidos_de_jugador(jugador, partidos)
    if not juegos:
        return 0.0
    return sum(1 for p in juegos if p["ganador"] == jugador) / len(juegos)


def calcular_pct_barrido_ganando(jugador, partidos):
    victorias = [p for p in partidos_de_jugador(jugador, partidos) if p["ganador"] == jugador]
    if not victorias:
        return 0.0
    return sum(1 for p in victorias if p["sets_perdedor"] == 0) / len(victorias)


def calcular_pct_fue_barrido(jugador, partidos):
    derrotas = [p for p in partidos_de_jugador(jugador, partidos) if p["perdedor"] == jugador]
    if not derrotas:
        return 0.0
    return sum(1 for p in derrotas if p["sets_perdedor"] == 0) / len(derrotas)


def h2h_detalle(a, b, partidos):
    enfrentamientos = [p for p in partidos if {p["jugador_a"], p["jugador_b"]} == {a, b}]
    enfrentamientos.sort(key=lambda p: p["time"])
    if not enfrentamientos:
        return {"n": 0, "ultima_fecha": None}
    ultimo = enfrentamientos[-1]
    if ultimo["time"]:
        fecha = datetime.datetime.fromtimestamp(ultimo["time"]).strftime("%d/%m/%Y")
    else:
        fecha = "desconocida"
    return {"n": len(enfrentamientos), "ultima_fecha": fecha}


def main():
    print("Cargando historico acumulado guardado...")
    historico_guardado = cargar_historico()
    primera_vez = len(historico_guardado) == 0
    paginas_por_liga = 60 if primera_vez else 5
    if primera_vez:
        print("  (reconstruyendo historico con detalle de sets, puede tardar varios minutos)")

    for nombre_liga, league_id in LIGAS.items():
        eventos = obtener_partidos_finalizados(league_id, paginas=paginas_por_liga)
        nuevos = 0
        for ev in eventos:
            eid = str(ev.get("id"))
            if eid in historico_guardado:
                continue
            p = parsear_partido(ev)
            if p:
                historico_guardado[eid] = p
                nuevos += 1
        print(f"  {nombre_liga}: {nuevos} partidos nuevos anadidos")

    guardar_historico(historico_guardado)
    todos_partidos = list(historico_guardado.values())
    print(f"\nTotal partidos historicos acumulados: {len(todos_partidos)}")

    jugadores = {}
    actualizar_elo(jugadores, todos_partidos)
    print(f"Jugadores con rating calculado: {len(jugadores)}")

    print("\nBuscando proximos partidos...")
    candidatas = []
    for nombre_liga, league_id in LIGAS.items():
        proximos = obtener_partidos_proximos(league_id, paginas=6)

        ultima_hora_jugador = {}
        for ev in proximos:
            h = ev.get("home", {}).get("name")
            a = ev.get("away", {}).get("name")
            try:
                ts_ev = int(ev.get("time"))
            except (TypeError, ValueError):
                continue
            for jugador in (h, a):
                if jugador:
                    ultima_hora_jugador[jugador] = max(ultima_hora_jugador.get(jugador, 0), ts_ev)

        for ev in proximos:
            home = ev.get("home", {}).get("name")
            away = ev.get("away", {}).get("name")
            event_id = ev.get("id")
            hora_raw = ev.get("time")
            try:
                hora_ts = int(hora_raw)
                hora_dt_madrid = datetime.datetime.fromtimestamp(hora_ts, tz=MADRID_TZ)
                hora = hora_dt_madrid.strftime("%H:%M")
            except (TypeError, ValueError):
                hora_ts = 999999999999
                hora = "--:--"
                hora_dt_madrid = None
            if not home or not away:
                continue

            if hora_dt_madrid is not None and not (8 <= hora_dt_madrid.hour < 23):
                continue

            p_home, n_h2h = prob_jugador_gana_set(home, away, todos_partidos)
            p_away, _ = prob_jugador_gana_set(away, home, todos_partidos)
            p_ambos = p_home * p_away
            color = color_semaforo(p_ambos)
            if color is None:
                continue

            p_1_1, _ = prob_patron(home, away, todos_partidos, patron_1_1_al_2do_set)
            p_3er, _ = prob_patron(home, away, todos_partidos, patron_disputado_3er_set)
            p_3_0, _ = prob_patron(home, away, todos_partidos, patron_termina_3_0)
            p_4mas, _ = prob_patron(home, away, todos_partidos, patron_4_mas_sets)

            h2h_info = h2h_detalle(home, away, todos_partidos)

            ultimo_torneo = (
                hora_ts >= ultima_hora_jugador.get(home, 0)
                and hora_ts >= ultima_hora_jugador.get(away, 0)
            )

            candidatas.append({
                "ultimo_torneo": ultimo_torneo,
                "liga": nombre_liga, "home": home, "away": away,
                "probabilidad": p_ambos, "color": color, "n_h2h": n_h2h,
                "p_home_individual": p_home, "p_away_individual": p_away,
                "hora": hora, "event_id": event_id, "hora_ts": hora_ts,
                "impulso_home": calcular_impulso(home, todos_partidos),
                "impulso_away": calcular_impulso(away, todos_partidos),
                "racha_home": calcular_racha(home, todos_partidos),
                "racha_away": calcular_racha(away, todos_partidos),
                "tasa_home": calcular_tasa_victorias(home, todos_partidos),
                "tasa_away": calcular_tasa_victorias(away, todos_partidos),
                "barrido_home": calcular_pct_barrido_ganando(home, todos_partidos),
                "barrido_away": calcular_pct_barrido_ganando(away, todos_partidos),
                "fue_barrido_home": calcular_pct_fue_barrido(home, todos_partidos),
                "fue_barrido_away": calcular_pct_fue_barrido(away, todos_partidos),
                "h2h_ultima_fecha": h2h_info["ultima_fecha"],
                "senal_1_1": p_1_1, "senal_3er": p_3er,
                "senal_3_0": p_3_0, "senal_4mas": p_4mas,
            })

    candidatas.sort(key=lambda x: x["probabilidad"], reverse=True)
    principales = candidatas[:TOP_N]

    ids_principales = {(c["home"], c["away"], c["hora_ts"]) for c in principales}
    extra_bajo_riesgo = [
        c for c in candidatas[TOP_N:]
        if c["senal_3_0"] <= 0.10 and (c["home"], c["away"], c["hora_ts"]) not in ids_principales
    ]

    seleccion = principales + extra_bajo_riesgo
    seleccion.sort(key=lambda x: x["hora_ts"])

    print(f"\n{'='*70}")
    print(f"TOP {TOP_N} SEÑALES DEL DIA (de {len(candidatas)} candidatas con umbral >=60%)")
    print(f"{'='*70}")
    simbolo = {"VERDE": "🟢", "AMARILLO": "🟡", "ROJO": "🔴"}
    for s in seleccion:
        print(f"{simbolo[s['color']]} {s['hora']}  {s['liga']:18s} {s['home']:20s} vs {s['away']:20s} | Ambos ganan set: {s['probabilidad']*100:5.1f}%  [P({s['home']})={s['p_home_individual']*100:.1f}% · P({s['away']})={s['p_away_individual']*100:.1f}%] (H2H n={s['n_h2h']})")

    if not seleccion:
        print("No se encontraron señales sobre el umbral con los partidos próximos disponibles ahora mismo.")

    return seleccion


def formatear_mensaje_individual(s):
    emoji_color = {"VERDE": "🟢", "AMARILLO": "🟡", "ROJO": "🔴"}
    etiqueta_color = {"VERDE": "💪 FUERTE", "AMARILLO": "⭐ ELITE", "ROJO": "🔸 SEÑAL"}
    aviso_home = " ⚠️" if s['racha_home'] <= -3 else ""
    aviso_away = " ⚠️" if s['racha_away'] <= -3 else ""
    fecha_h2h = s['h2h_ultima_fecha'] or "sin enfrentamientos previos"

    bandera = "  🏁" if s.get("ultimo_torneo") else ""
    lineas = [
        f"{emoji_color[s['color']]} {s['liga']}  |  {etiqueta_color[s['color']]}  |  ⏳ empieza en 1h{bandera}",
        f"🕐 {s['hora']}  ·  {s['home']} vs {s['away']}",
        f"🎾 Ambos ganan set: {s['probabilidad']*100:.1f}%",
        f"📈 Impulso: {s['home']} {s['impulso_home']*100:+.0f}%  ·  {s['away']} {s['impulso_away']*100:+.0f}%",
        f"🔥 Racha: {s['home']} {s['racha_home']:+d}{aviso_home}  ·  {s['away']} {s['racha_away']:+d}{aviso_away}",
        f"🏆 Tasa victorias: {s['home']} {s['tasa_home']*100:.0f}%  ·  {s['away']} {s['tasa_away']*100:.0f}%",
        f"🧹 % barrido 3-0 (ganando): {s['home']} {s['barrido_home']*100:.0f}%  ·  {s['away']} {s['barrido_away']*100:.0f}%",
        f"💥 % fue barrido 0-3: {s['home']} {s['fue_barrido_home']*100:.0f}%  ·  {s['away']} {s['fue_barrido_away']*100:.0f}%",
        f"🤝 H2H: {s['n_h2h']} partidos (ultimo: {fecha_h2h})",
        f"🔑 Señales: 1-1 al 2do set {s['senal_1_1']*100:.0f}%  ·  llega al 3er set {s['senal_3er']*100:.0f}%  ·  termina 3-0 {s['senal_3_0']*100:.0f}%  ·  4+ sets {s['senal_4mas']*100:.0f}%",
    ]
    return "\n".join(lineas)


def formatear_mensaje_actualizacion(s, prob_anterior):
    emoji_color = {"VERDE": "🟢", "AMARILLO": "🟡", "ROJO": "🔴"}
    diferencia = (s["probabilidad"] - prob_anterior) * 100
    flecha = "📈" if diferencia > 0 else ("📉" if diferencia < 0 else "➡️")
    fecha_h2h = s['h2h_ultima_fecha'] or "sin enfrentamientos previos"

    bandera = "  🏁" if s.get("ultimo_torneo") else ""
    lineas = [
        f"🔄 ACTUALIZACIÓN  |  {emoji_color[s['color']]} {s['liga']}{bandera}",
        f"🕐 {s['hora']}  ·  {s['home']} vs {s['away']}",
        f"🎾 Ambos ganan set: {s['probabilidad']*100:.1f}%  {flecha} ({diferencia:+.1f} pts desde el ultimo aviso)",
        f"📈 Impulso: {s['home']} {s['impulso_home']*100:+.0f}%  ·  {s['away']} {s['impulso_away']*100:+.0f}%",
        f"🔥 Racha: {s['home']} {s['racha_home']:+d}  ·  {s['away']} {s['racha_away']:+d}",
        f"🤝 H2H: {s['n_h2h']} partidos (ultimo: {fecha_h2h})",
        f"🔑 Termina 3-0: {s['senal_3_0']*100:.0f}%  ·  4+ sets: {s['senal_4mas']*100:.0f}%",
    ]
    return "\n".join(lineas)


ARCHIVO_ACTUALIZACIONES = "ultima_actualizacion.json"


def cargar_actualizaciones():
    import json
    import os
    if not os.path.exists(ARCHIVO_ACTUALIZACIONES):
        return {}
    try:
        with open(ARCHIVO_ACTUALIZACIONES, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def guardar_actualizaciones(datos):
    import json
    with open(ARCHIVO_ACTUALIZACIONES, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False)


def enviar_actualizaciones_periodicas(seleccion):
    actualizaciones = cargar_actualizaciones()
    ahora = time.time()
    intervalo = 2.5 * 3600
    enviadas = 0

    ids_vistos = set()
    for s in seleccion:
        eid = str(s.get("event_id"))
        if not eid or eid == "None":
            continue
        ids_vistos.add(eid)
        if s["hora_ts"] <= ahora:
            continue

        anterior = actualizaciones.get(eid)
        if anterior is None:
            actualizaciones[eid] = {"prob": s["probabilidad"], "ts": ahora}
            continue

        if ahora - anterior["ts"] >= intervalo:
            mensaje = formatear_mensaje_actualizacion(s, anterior["prob"])
            enviar_telegram(mensaje)
            actualizaciones[eid] = {"prob": s["probabilidad"], "ts": ahora}
            enviadas += 1

    actualizaciones_limpias = {eid: v for eid, v in actualizaciones.items() if eid in ids_vistos}
    guardar_actualizaciones(actualizaciones_limpias)

    print(f"Actualizaciones periodicas enviadas en esta ejecucion: {enviadas}")
    return enviadas ARCHIVO_AVISOS = "avisos_enviados.json"


def cargar_avisos():
    import json
    import os
    if not os.path.exists(ARCHIVO_AVISOS):
        return {}
    try:
        with open(ARCHIVO_AVISOS, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def guardar_avisos(avisos):
    import json
    with open(ARCHIVO_AVISOS, "w", encoding="utf-8") as f:
        json.dump(avisos, f, ensure_ascii=False)


def enviar_avisos_pendientes(seleccion):
    avisos = cargar_avisos()
    ahora = time.time()
    ventana_previa = 3600
    enviados_ahora = 0

    for s in seleccion:
        eid = str(s.get("event_id"))
        if not eid or eid == "None":
            continue
        if eid in avisos:
            continue
        tiempo_partido = s["hora_ts"]
        if tiempo_partido - ventana_previa <= ahora < tiempo_partido:
            mensaje = formatear_mensaje_individual(s)
            enviar_telegram(mensaje)
            avisos[eid] = True
            enviados_ahora += 1

    avisos_limpios = {}
    ids_seleccion = {str(s.get("event_id")): s["hora_ts"] for s in seleccion if s.get("event_id")}
    for eid, valor in avisos.items():
        hora_evento = ids_seleccion.get(eid)
        if hora_evento is None or ahora - hora_evento < 86400:
            avisos_limpios[eid] = valor
    guardar_avisos(avisos_limpios)

    print(f"Avisos individuales enviados en esta ejecucion: {enviados_ahora}")
    return enviados_ahora


if __name__ == "__main__":
    import sys
    import io
    import os as os_lock

    ARCHIVO_CANDADO = "ejecucion_en_curso.lock"

    if os_lock.path.exists(ARCHIVO_CANDADO):
        edad_candado = time.time() - os_lock.path.getmtime(ARCHIVO_CANDADO)
        if edad_candado < 900:
            print("Ya hay una ejecucion en curso, se cancela esta para evitar duplicados.")
            sys.exit(0)

    with open(ARCHIVO_CANDADO, "w", encoding="utf-8") as f:
        f.write(str(time.time()))

    try:
        comprobar_predicciones_anteriores()

        buffer = io.StringIO()
        stdout_original = sys.stdout
        sys.stdout = buffer
        try:
            seleccion_hoy = main()
        finally:
            sys.stdout = stdout_original

        salida = buffer.getvalue()
        print(salida)

        if seleccion_hoy:
            pendientes = cargar_pendientes()
            notificados = cargar_resultados_notificados()
            for s in seleccion_hoy:
                eid = s.get("event_id")
                if eid and str(eid) not in notificados:
                    pendientes[str(eid)] = s
            guardar_pendientes(pendientes)

        fecha = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
        nombre_archivo = f"senales_{fecha}.txt"
        with open(nombre_archivo, "w", encoding="utf-8") as f:
            f.write(f"Señales generadas el {datetime.datetime.now().strftime('%d/%m/%Y a las %H:%M')}\n\n")
            f.write(salida)
        print(f"\nGuardado en: {nombre_archivo}")

        fecha_hora_str = datetime.datetime.now().strftime('%d/%m %H:%M')
        enviar_avisos_pendientes(seleccion_hoy)
        print("Avisos individuales revisados.")
        enviar_actualizaciones_periodicas(seleccion_hoy)

        limpiar_archivos_antiguos(dias=7)
    finally:
        if os_lock.path.exists(ARCHIVO_CANDADO):
            os_lock.remove(ARCHIVO_CANDADO)
