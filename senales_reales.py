"""
Motor de senales de tenis de mesa con datos reales de BetsAPI.
Version con paquete completo: impulso, racha, % barridos, H2H detallado,
señales clave, chequeo de consistencia, ultimo del torneo y actualizaciones
periodicas.
"""

import os
import requests
import time
import datetime
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo
from supabase_bridge import guardar_senales_supabase, guardar_estadisticas_supabase, guardar_resultado_supabase, obtener_signals_sin_resultado

MADRID_TZ = ZoneInfo("Europe/Madrid")

TOKEN = os.environ["BETSAPI_TOKEN"]
BASE_URL = "https://api.b365api.com/v1"
SPORT_ID_TENIS_MESA = 92

LIGAS = {
    "TT Elite Series": 29128,
    "Setka Cup": 22307,
    "Czech Liga Pro": 22742,
    "TT Cup": 29097,
}

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_IDS = ["663483538", "-1004364860113"]

TOP_N = 25
MAX_SELECCION_DIARIA = 35


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
ARCHIVO_BACKFILL = "backfill_estado.json"
PRESUPUESTO_BACKFILL_SEGUNDOS = 240


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


def cargar_backfill_estado():
    import json
    import os
    if not os.path.exists(ARCHIVO_BACKFILL):
        return {}
    try:
        with open(ARCHIVO_BACKFILL, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def guardar_backfill_estado(estado):
    import json
    with open(ARCHIVO_BACKFILL, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False)


def backfill_historico(league_id, nombre_liga, estado, presupuesto_segundos):
    """Sigue paginando events/ended mas alla de lo que cubre el fetch normal
    (paginas_por_liga), retomando en cada corrida desde la ultima pagina
    alcanzada la vez anterior, para ir completando poco a poco el historico
    real de ligas muy activas (p. ej. TT Elite Series, con cientos de miles
    de partidos, donde 150 paginas por corrida solo cubre una fraccion
    minima). No se pierde nada: el progreso (numero de pagina) se guarda en
    disco despues de cada corrida y los partidos se combinan por id, asi que
    aunque la paginacion se solape un poco entre corridas nunca se pierde
    historico, solo se puede re-procesar algo ya visto (inofensivo)."""
    info = estado.setdefault(nombre_liga, {"pagina_actual": 150, "agotado": False})
    if info.get("agotado"):
        return []

    partidos = []
    page = info.get("pagina_actual", 150) + 1
    inicio = time.time()

    while time.time() - inicio < presupuesto_segundos:
        intentos = 0
        resp = None
        while intentos < 2:
            try:
                resp = requests.get(f"{BASE_URL}/events/ended", params={
                    "token": TOKEN, "sport_id": SPORT_ID_TENIS_MESA,
                    "league_id": league_id, "page": page,
                }, timeout=20)
                break
            except requests.exceptions.RequestException:
                intentos += 1
                if intentos < 2:
                    time.sleep(2)
        if resp is None:
            print(f"  (backfill {nombre_liga}: sin respuesta en pagina {page}, seguimos en la proxima corrida)")
            break
        try:
            data = resp.json()
        except ValueError:
            print(f"  (backfill {nombre_liga}: respuesta invalida en pagina {page}, seguimos en la proxima corrida)")
            break

        resultados = data.get("results") or []
        if not resultados:
            info["agotado"] = True
            print(f"  (backfill {nombre_liga}: completado, no hay mas historico despues de la pagina {page - 1})")
            break

        partidos.extend(resultados)
        info["pagina_actual"] = page
        page += 1
        time.sleep(0.2)

    return partidos


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
    except requests.exceptions.RequestException as e:
        print(f"  (DIAG resultado {event_id}: fallo de red en event/view: {e})")
        return None
    if resp.status_code != 200:
        print(f"  (DIAG resultado {event_id}: event/view respondio HTTP {resp.status_code}: {resp.text[:300]})")
    try:
        data = resp.json()
    except ValueError as e:
        print(f"  (DIAG resultado {event_id}: respuesta no es JSON valido ({e}): {resp.text[:300]})")
        return None
    if not data.get("success") or not data.get("results"):
        print(f"  (DIAG resultado {event_id}: BetsAPI success={data.get('success')!r} results={data.get('results')!r} data={str(data)[:300]})")
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
    print(f"  (DIAG resultado: comprobando {len(pendientes)} predicciones pendientes)")
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
            hora_ts_pred = pred.get("hora_ts")
            if hora_ts_pred and (time.time() - hora_ts_pred) > 6 * 3600:
                print(f"  (DIAG resultado {event_id}: time_status={detalle.get('time_status')!r} sigue sin ser 3 y el partido era de hace mas de 6h (hora_ts={hora_ts_pred}); BetsAPI probablemente lo cancelo/pospuso/interrumpio, se descarta sin resultado ni aviso para que no quede pendiente para siempre)")
                continue
            print(f"  (DIAG resultado {event_id}: time_status={detalle.get('time_status')!r} time={detalle.get('time')!r} ss={detalle.get('ss')!r} home={detalle.get('home')!r} away={detalle.get('away')!r})")
            aun_pendientes[event_id] = pred
            continue
        resultado = parsear_partido(detalle)
        if resultado is None:
            print(f"  (DIAG resultado {event_id}: time_status=3 pero parsear_partido devolvio None, se descarta la senal sin guardar resultado; ss={detalle.get('ss')!r} scores={str(detalle.get('scores'))[:200]})")
            continue
        if resultado["ganador"] == resultado["jugador_a"]:
            sets_home, sets_away = resultado["sets_ganador"], resultado["sets_perdedor"]
        else:
            sets_home, sets_away = resultado["sets_perdedor"], resultado["sets_ganador"]
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

        fecha_partido = (
            datetime.datetime.fromtimestamp(pred["hora_ts"], tz=MADRID_TZ).strftime("%Y-%m-%d")
            if pred.get("hora_ts")
            else datetime.date.today().isoformat()
        )
        guardar_resultado_supabase({
            "event_id": event_id,
            "liga": pred.get("liga"),
            "home": pred.get("home"),
            "away": pred.get("away"),
            "acierto": acerto,
            "probabilidad": pred.get("probabilidad"),
            "color": pred.get("color"),
            "hora_ts": pred.get("hora_ts"),
            "sets_home": sets_home,
            "sets_away": sets_away,
            "fecha": fecha_partido,
        })
        notificados[event_id] = True
    resueltas = len(pendientes) - len(aun_pendientes)
    print(f"  (DIAG resultado: {resueltas} resueltas en esta ejecucion, {len(aun_pendientes)} siguen pendientes)")
    guardar_pendientes(aun_pendientes)
    guardar_resultados_notificados(notificados)
    guardar_estadisticas(estadisticas)
    guardar_estadisticas_supabase(estadisticas)

def reconciliar_senales_huerfanas():
    """Red de seguridad contra señales huerfanas: usa Supabase (tabla
    `signals`, escrita por HTTP, independiente de si el commit de git de
    esa ejecucion consiguio hacer push) en vez de
    predicciones_pendientes.json (que vive solo en el checkout local de
    cada ejecucion y puede perder una señal si ese push fallo, o si el
    partido ya no aparece en events/upcoming de BetsAPI la siguiente vez
    que main() corre, con lo que nunca vuelve a tener otra oportunidad de
    entrar en pendientes). Sin esto, esas señales quedan visibles en el
    dashboard via `signals` pero sin marcador para siempre.

    No manda avisos de Telegram: son partidos que ya sucedieron hace
    tiempo si llegaron hasta aqui, y avisar ahora seria confuso. Solo
    rellena el resultado que falte en Supabase."""
    try:
        huerfanas = obtener_signals_sin_resultado(horas_atras=72)
    except Exception as e:
        print(f"  (DIAG reconciliacion: fallo inesperado obteniendo señales huerfanas: {e})")
        return

    if not huerfanas:
        return

    print(f"  (DIAG reconciliacion: {len(huerfanas)} señales sin resultado en Supabase, comprobando BetsAPI...)")
    reparadas = 0
    for s in huerfanas:
        event_id = str(s.get("event_id") or "")
        if not event_id or event_id == "None":
            continue
        detalle = obtener_resultado_partido(event_id)
        if detalle is None:
            continue
        if str(detalle.get("time_status")) != "3":
            hora_ts_s = s.get("hora_ts")
            if hora_ts_s and (time.time() - hora_ts_s) > 6 * 3600:
                print(f"  (DIAG reconciliacion {event_id}: time_status={detalle.get('time_status')!r} sigue sin ser 3 y el partido era de hace mas de 6h, probablemente cancelado/pospuesto, se omite)")
                continue
            print(f"  (DIAG reconciliacion {event_id}: time_status={detalle.get('time_status')!r} time={detalle.get('time')!r} ss={detalle.get('ss')!r})")
            continue
        resultado = parsear_partido(detalle)
        if resultado is None:
            print(f"  (DIAG reconciliacion {event_id}: time_status=3 pero parsear_partido devolvio None, se omite; ss={detalle.get('ss')!r})")
            continue
        if resultado["ganador"] == resultado["jugador_a"]:
            sets_home, sets_away = resultado["sets_ganador"], resultado["sets_perdedor"]
        else:
            sets_home, sets_away = resultado["sets_perdedor"], resultado["sets_ganador"]
        acerto = resultado["sets_perdedor"] >= 1
        hora_ts = s.get("hora_ts")
        fecha_partido = (
            datetime.datetime.fromtimestamp(hora_ts, tz=MADRID_TZ).strftime("%Y-%m-%d")
            if hora_ts else datetime.date.today().isoformat()
        )
        guardar_resultado_supabase({
            "event_id": event_id,
            "liga": s.get("liga"),
            "home": s.get("home"),
            "away": s.get("away"),
            "acierto": acerto,
            "probabilidad": s.get("probabilidad"),
            "color": s.get("color"),
            "hora_ts": hora_ts,
            "sets_home": sets_home,
            "sets_away": sets_away,
            "fecha": fecha_partido,
        })
        reparadas += 1
    print(f"  (DIAG reconciliacion: {reparadas}/{len(huerfanas)} señales huerfanas reparadas)")


def obtener_partidos_finalizados(league_id, paginas=3, historico_conocido=None):
    partidos = []
    page = 1
    inicio = time.time()
    presupuesto_segundos = 90
    while page <= paginas:
        if time.time() - inicio > presupuesto_segundos:
            print(f" (aviso: presupuesto de tiempo agotado para esta liga, corto en pagina {page})")
            break
        intentos = 0
        resp = None
        while intentos < 2:
            try:
                resp = requests.get(f"{BASE_URL}/events/ended", params={
                    "token": TOKEN, "sport_id": SPORT_ID_TENIS_MESA,
                    "league_id": league_id, "page": page,
                }, timeout=20)
                break
            except requests.exceptions.RequestException:
                intentos += 1
                if intentos < 2:
                    print(f" (aviso: tiempo de espera agotado en pagina {page}, reintento)")
                    time.sleep(2)
                else:
                    print(f" (aviso: tiempo de espera agotado en pagina {page} tras reintento, me detengo aqui)")
        if resp is None:
            break
        try:
            data = resp.json()
        except ValueError:
            print(" (aviso: respuesta no valida de la API, esperando y continuando)")
            time.sleep(3)
            break
        if not data.get("success") or not data.get("results"):
            break
        partidos.extend(data["results"])
        if historico_conocido is not None and data["results"] and all(str(ev.get("id")) in historico_conocido for ev in data["results"]):
            print(f" (pagina {page}: sin partidos nuevos, ya al dia, freno aqui)")
            break
        time.sleep(0.2)
        page += 1
    return partidos


def obtener_partidos_proximos(league_id, paginas=3):
    partidos = []
    page = 1
    inicio = time.time()
    presupuesto_segundos = 45
    while page <= paginas:
        if time.time() - inicio > presupuesto_segundos:
            print(f" (aviso: presupuesto de tiempo agotado buscando proximos para esta liga, corto en pagina {page})")
            break
        intentos = 0
        resp = None
        while intentos < 2:
            try:
                resp = requests.get(f"{BASE_URL}/events/upcoming", params={
                    "token": TOKEN, "sport_id": SPORT_ID_TENIS_MESA,
                    "league_id": league_id, "page": page,
                }, timeout=20)
                break
            except requests.exceptions.RequestException:
                intentos += 1
                if intentos < 2:
                    print(f" (aviso: tiempo de espera agotado buscando proximos en pagina {page}, reintento)")
                    time.sleep(2)
                else:
                    print(f" (aviso: tiempo de espera agotado buscando proximos en pagina {page} tras reintento, me detengo aqui)")
        if resp is None:
            break
        try:
            data = resp.json()
        except ValueError:
            break
        if not data.get("success") or not data.get("results"):
            break
        partidos.extend(data["results"])
        time.sleep(0.3)
        page += 1
    return partidos
MAX_BUSQUEDAS_DIRECTAS_POR_EJECUCION = 15


def obtener_partidos_por_jugador(team_id, paginas=2):
    partidos = []
    for page in range(1, paginas + 1):
        try:
            resp = requests.get(f"{BASE_URL}/events/ended", params={
                "token": TOKEN, "sport_id": SPORT_ID_TENIS_MESA,
                "team_id": team_id, "page": page,
            }, timeout=15)
            data = resp.json()
        except Exception:
            break
        if not data.get("success") or not data.get("results"):
            break
        partidos.extend(data["results"])
        time.sleep(0.2)
    return partidos


def completar_historico_jugador(team_id, nombre, historico_guardado, todos_partidos):
    if not team_id:
        return 0
    nuevos = 0
    for ev in obtener_partidos_por_jugador(team_id):
        eid = str(ev.get("id"))
        if eid in historico_guardado:
            continue
        p = parsear_partido(ev)
        if p:
            historico_guardado[eid] = p
            todos_partidos.append(p)
            nuevos += 1
    if nuevos:
        print(f"   (busqueda directa de {nombre}: +{nuevos} partidos anadidos)")
    return nuevos


def parsear_partido(evento):
    home = evento.get("home", {}).get("name")
    away = evento.get("away", {}).get("name")
    home_id = evento.get("home", {}).get("id")
    away_id = evento.get("away", {}).get("id")
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
        "jugador_a_id": home_id, "jugador_b_id": away_id,
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
    if p >= 0.65:
        return "ROJO"
    return None


def calcular_impulso(jugador, partidos, n_reciente=20):
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


ARCHIVO_SELECCION_DIARIA = "seleccion_diaria.json"

def cargar_seleccion_diaria():
    import json
    import os
    hoy = datetime.datetime.now(MADRID_TZ).strftime("%Y-%m-%d")
    if not os.path.exists(ARCHIVO_SELECCION_DIARIA):
        return {"fecha": hoy, "event_ids": []}
    try:
        with open(ARCHIVO_SELECCION_DIARIA, "r", encoding="utf-8") as f:
            datos = json.load(f)
        if datos.get("fecha") != hoy:
            return {"fecha": hoy, "event_ids": []}
        return datos
    except Exception:
        return {"fecha": hoy, "event_ids": []}

def guardar_seleccion_diaria(datos):
    import json
    with open(ARCHIVO_SELECCION_DIARIA, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False)

def main():
    print("Cargando historico acumulado guardado...")
    historico_guardado = cargar_historico()
    primera_vez = len(historico_guardado) == 0
    paginas_por_liga = 150
    if primera_vez:
        print("  (reconstruyendo historico con detalle de sets, puede tardar varios minutos)")

    backfill_estado = cargar_backfill_estado()

    for nombre_liga, league_id in LIGAS.items():
        eventos = obtener_partidos_finalizados(league_id, paginas=paginas_por_liga, historico_conocido=historico_guardado)
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

        eventos_backfill = backfill_historico(league_id, nombre_liga, backfill_estado, PRESUPUESTO_BACKFILL_SEGUNDOS)
        nuevos_backfill = 0
        for ev in eventos_backfill:
            eid = str(ev.get("id"))
            if eid in historico_guardado:
                continue
            p = parsear_partido(ev)
            if p:
                historico_guardado[eid] = p
                nuevos_backfill += 1
        info_liga = backfill_estado.get(nombre_liga, {})
        print(f"  {nombre_liga}: backfill anadio {nuevos_backfill} partidos historicos (pagina {info_liga.get('pagina_actual')}, agotado={info_liga.get('agotado')})")

    guardar_historico(historico_guardado)
    guardar_backfill_estado(backfill_estado)
    todos_partidos = list(historico_guardado.values())
    print(f"\nTotal partidos historicos acumulados: {len(todos_partidos)}")

    jugadores = {}
    actualizar_elo(jugadores, todos_partidos)
    print(f"Jugadores con rating calculado: {len(jugadores)}")

    print("\nBuscando proximos partidos...")
    candidatas = []
    busquedas_directas_restantes = MAX_BUSQUEDAS_DIRECTAS_POR_EJECUCION
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

            if hora_dt_madrid is not None:
                if hora_dt_madrid.date() != datetime.datetime.now(MADRID_TZ).date():
                    continue
                if not (8 <= hora_dt_madrid.hour < 23):
                    continue

            n_partidos_home = len(partidos_de_jugador(home, todos_partidos))
            n_partidos_away = len(partidos_de_jugador(away, todos_partidos))
            if (n_partidos_home < 15 or n_partidos_away < 15) and busquedas_directas_restantes > 0:
                home_id = ev.get("home", {}).get("id")
                away_id = ev.get("away", {}).get("id")
                if n_partidos_home < 15 and home_id and busquedas_directas_restantes > 0:
                    completar_historico_jugador(home_id, home, historico_guardado, todos_partidos)
                    busquedas_directas_restantes -= 1
                if n_partidos_away < 15 and away_id and busquedas_directas_restantes > 0:
                    completar_historico_jugador(away_id, away, historico_guardado, todos_partidos)
                    busquedas_directas_restantes -= 1
                n_partidos_home = len(partidos_de_jugador(home, todos_partidos))
                n_partidos_away = len(partidos_de_jugador(away, todos_partidos))
            if n_partidos_home < 15 or n_partidos_away < 15:
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

            consistencia = abs((p_ambos + p_3_0) - 1.0)
            discrepancia = consistencia > 0.12

            ultimo_torneo = (
                hora_ts >= ultima_hora_jugador.get(home, 0)
                and hora_ts >= ultima_hora_jugador.get(away, 0)
            )

            # Puntuacion combinada: probabilidad principal, penalizada por riesgo
            # de barrida, y con pequeños extras por partidos reñidos (4+ sets)
            # y por tener mas historial H2H directo (mas fiable)
            score = (
                p_ambos
                - p_3_0
                + (0.05 * p_4mas)
                + (0.05 * min(n_h2h, 20) / 20)
            )

            candidatas.append({
                "liga": nombre_liga, "home": home, "away": away,
                "probabilidad": p_ambos, "score": score, "color": color, "n_h2h": n_h2h,
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
                "discrepancia": discrepancia,
                "ultimo_torneo": ultimo_torneo,
            })

    guardar_historico(historico_guardado)
    candidatas.sort(key=lambda x: x["score"], reverse=True)

    seleccion_diaria = cargar_seleccion_diaria()
    ids_bloqueados_hoy = set(seleccion_diaria["event_ids"])

    ya_elegidas_hoy = [c for c in candidatas if str(c["event_id"]) in ids_bloqueados_hoy]
    candidatas_nuevas = [c for c in candidatas if str(c["event_id"]) not in ids_bloqueados_hoy]

    huecos_libres_hoy = max(0, MAX_SELECCION_DIARIA - len(ids_bloqueados_hoy))
    nuevas_admitidas = candidatas_nuevas[:huecos_libres_hoy]

    seleccion = ya_elegidas_hoy + nuevas_admitidas
    seleccion.sort(key=lambda x: x["hora_ts"])

    ids_bloqueados_hoy |= {str(c["event_id"]) for c in nuevas_admitidas if c.get("event_id")}
    seleccion_diaria["event_ids"] = list(ids_bloqueados_hoy)
    guardar_seleccion_diaria(seleccion_diaria)

    print(f"\n{'='*70}")
    print(f"SELECCION DE HOY: {len(ids_bloqueados_hoy)}/{MAX_SELECCION_DIARIA} partidos bloqueados para el dia (primeros {TOP_N} intocables + hasta {MAX_SELECCION_DIARIA - TOP_N} extra si aparecen mejores candidatos; de {len(candidatas)} candidatas esta ejecucion, umbral >=65%)")
    print(f"{'='*70}")
    simbolo = {"VERDE": "🟢", "AMARILLO": "🟡", "ROJO": "🔴"}
    for s in seleccion:
        print(f"{simbolo[s['color']]} {s['hora']}  {s['liga']:18s} {s['home']:20s} vs {s['away']:20s} | Ambos ganan set: {s['probabilidad']*100:5.1f}%  [P({s['home']})={s['p_home_individual']*100:.1f}% · P({s['away']})={s['p_away_individual']*100:.1f}%] (H2H n={s['n_h2h']})")

    if not seleccion:
        print("No se encontraron señales sobre el umbral con los partidos próximos disponibles ahora mismo.")

    return seleccion


def formatear_mensaje_individual(s, ahora=None):
    emoji_color = {"VERDE": "🟢", "AMARILLO": "🟡", "ROJO": "🔴"}
    etiqueta_color = {"VERDE": "💪 FUERTE", "AMARILLO": "⭐ ELITE", "ROJO": "🔸 SEÑAL"}
    aviso_home = " ⚠️" if s['racha_home'] <= -3 else ""
    aviso_away = " ⚠️" if s['racha_away'] <= -3 else ""
    fecha_h2h = s['h2h_ultima_fecha'] or "sin enfrentamientos previos"
    bandera = "  🏁" if s.get("ultimo_torneo") else ""
    discrepancia_txt = "\n⚠️ DISCREPANCIA: nuestros modelos internos no coinciden del todo, señal menos fiable" if s.get("discrepancia") else ""

    if ahora is not None:
        restante_min = max(0, round((s['hora_ts'] - ahora) / 60))
        texto_cuenta = "empieza en menos de 1 min" if restante_min <= 1 else f"empieza en {restante_min} min"
    else:
        texto_cuenta = "empieza en 1h"
    lineas = [
        f"{emoji_color[s['color']]} {s['liga']}  |  {etiqueta_color[s['color']]}  |  ⏳ {texto_cuenta}{bandera}",
        f"🕐 {s['hora']}  ·  {s['home']} vs {s['away']}",
        f"🎾 Ambos ganan set: {s['probabilidad']*100:.1f}%",
        f"📈 Impulso: {s['home']} {s['impulso_home']*100:+.0f}%  ·  {s['away']} {s['impulso_away']*100:+.0f}%",
        f"🔥 Racha: {s['home']} {s['racha_home']:+d}{aviso_home}  ·  {s['away']} {s['racha_away']:+d}{aviso_away}",
        f"🏆 Tasa victorias: {s['home']} {s['tasa_home']*100:.0f}%  ·  {s['away']} {s['tasa_away']*100:.0f}%",
        f"🧹 % barrido 3-0 (ganando): {s['home']} {s['barrido_home']*100:.0f}%  ·  {s['away']} {s['barrido_away']*100:.0f}%",
        f"💥 % fue barrido 0-3: {s['home']} {s['fue_barrido_home']*100:.0f}%  ·  {s['away']} {s['fue_barrido_away']*100:.0f}%",
        f"🤝 H2H: {s['n_h2h']} partidos (ultimo: {fecha_h2h})",
        f"🔑 Señales: 1-1 al 2do set {s['senal_1_1']*100:.0f}%  ·  llega al 3er set {s['senal_3er']*100:.0f}%  ·  termina 3-0 {s['senal_3_0']*100:.0f}%  ·  4+ sets {s['senal_4mas']*100:.0f}%{discrepancia_txt}",
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
    ventana_actualizacion = 3600  # solo si falta 1 hora o menos para el partido
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
            actualizaciones[eid] = {"prob": s["probabilidad"], "enviada": False}
            continue

        if anterior.get("enviada"):
            continue

        restante = s["hora_ts"] - ahora
        if restante <= ventana_actualizacion:
            mensaje = formatear_mensaje_actualizacion(s, anterior["prob"])
            enviar_telegram(mensaje)
            actualizaciones[eid] = {"prob": s["probabilidad"], "enviada": True}
            enviadas += 1

    actualizaciones_limpias = {eid: v for eid, v in actualizaciones.items() if eid in ids_vistos}
    guardar_actualizaciones(actualizaciones_limpias)

    print(f"Actualizaciones periodicas enviadas en esta ejecucion: {enviadas}")
    return enviadas


ARCHIVO_RESUMEN_DIARIO = "resumen_diario_enviado.json"


def cargar_resumen_diario_estado():
    import json
    import os
    if not os.path.exists(ARCHIVO_RESUMEN_DIARIO):
        return {}
    try:
        with open(ARCHIVO_RESUMEN_DIARIO, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def guardar_resumen_diario_estado(datos):
    import json
    with open(ARCHIVO_RESUMEN_DIARIO, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False)


def enviar_resumen_diario(seleccion):
    ahora_madrid = datetime.datetime.now(MADRID_TZ)
    hoy = ahora_madrid.strftime("%Y-%m-%d")

    if ahora_madrid.hour < 8:
        return False

    estado = cargar_resumen_diario_estado()
    if estado.get("ultima_fecha") == hoy:
        return False

    ahora = time.time()
    proximas = [s for s in seleccion if s["hora_ts"] > ahora]
    proximas.sort(key=lambda x: x["hora_ts"])

    simbolo = {"VERDE": "🟢", "AMARILLO": "🟡", "ROJO": "🔴"}
    if proximas:
        lineas = [f"📋 RESUMEN DEL DIA — {hoy}", f"Mejores pronosticos de hoy ({len(proximas)}):", ""]
        for s in proximas:
            lineas.append(
                f"{simbolo[s['color']]} {s['hora']}  {s['liga']}  {s['home']} vs {s['away']} | "
                f"Ambos ganan set: {s['probabilidad']*100:.1f}%"
            )
        mensaje = "\n".join(lineas)
    else:
        mensaje = f"📋 RESUMEN DEL DIA — {hoy}\nNo hay señales sobre el umbral con los partidos disponibles ahora mismo."

    enviar_telegram(mensaje)
    estado["ultima_fecha"] = hoy
    guardar_resumen_diario_estado(estado)
    return True

ARCHIVO_AVISOS = "avisos_enviados.json"


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
            mensaje = formatear_mensaje_individual(s, ahora)
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
        reconciliar_senales_huerfanas()

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
            guardar_senales_supabase(seleccion_hoy)

        fecha = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
        nombre_archivo = f"senales_{fecha}.txt"
        with open(nombre_archivo, "w", encoding="utf-8") as f:
            f.write(f"Señales generadas el {datetime.datetime.now().strftime('%d/%m/%Y a las %H:%M')}\n\n")
            f.write(salida)
        print(f"\nGuardado en: {nombre_archivo}")

        enviar_avisos_pendientes(seleccion_hoy)
        print("Avisos individuales revisados.")

        enviar_actualizaciones_periodicas(seleccion_hoy)

        enviar_resumen_diario(seleccion_hoy)

        limpiar_archivos_antiguos(dias=7)
    finally:
        if os_lock.path.exists(ARCHIVO_CANDADO):
            os_lock.remove(ARCHIVO_CANDADO)
