"""
Motor de señales de "quién gana el primer set" para tenis de mesa.

Hermano de senales_reales.py: se ejecuta como paso siguiente en el mismo
workflow de GitHub Actions (senales.yml), sobre el mismo checkout, así que
reutiliza el historico_partidos.json que senales_reales.py acaba de dejar
actualizado en este mismo run (no vuelve a bajar nada de BetsAPI para
reconstruir el histórico). También reutiliza directamente las funciones
de carga/parseo/suavizado/H2H de senales_reales.py en vez de duplicarlas,
para no tener dos copias de esa lógica divergiendo con el tiempo.

Mide un evento distinto al de senales_reales.py: en vez de "¿ambos
jugadores ganan al menos un set?", esto es "¿quién se lleva el PRIMER
set del partido?". El historico_partidos.json ya trae el marcador set a
set (campo "sets", lista de [puntos_home, puntos_away] en orden), así
que sets[0] es exactamente el primer set — no hace falta ningún dato
nuevo, solo mirar esa posición.

Estado propio (no se mezcla con los archivos de senales_reales.py):
predicciones_pendientes_primer_set.json, resultados_notificados_primer_set.json,
estadisticas_primer_set.json, avisos_enviados_primer_set.json,
ultima_actualizacion_primer_set.json, resumen_diario_enviado_primer_set.json,
seleccion_diaria_primer_set.json.

También sube a Supabase (si SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY están
configurados) a sus propias tablas hermanas: signals_primer_set,
resultados_primer_set, daily_stats_primer_set — nunca a signals/
resultados/daily_stats, que son de la señal original. Estas tablas las
usa la pestaña "Primer set" del panel web (pulsopro-web).

Requiere las mismas variables de entorno que senales_reales.py
(BETSAPI_TOKEN, TELEGRAM_BOT_TOKEN) porque al importar funciones de ese
módulo se ejecuta su código de nivel superior — además necesita su
propio TELEGRAM_BOT_TOKEN_PRIMER_SET para mandar los avisos de esta
señal a un bot/chat separado.
"""

import os
import time
import datetime

import requests

from senales_reales import (
    LIGAS,
    MADRID_TZ,
    MAX_BUSQUEDAS_DIRECTAS_POR_EJECUCION,
    cargar_historico,
    guardar_historico,
    obtener_partidos_proximos,
    obtener_resultado_partido,
    parsear_partido,
    partidos_de_jugador,
    completar_historico_jugador,
    prop_suavizada,
    peso_h2h,
    resultado_set,
    h2h_detalle,
    color_semaforo,
)

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN_PRIMER_SET"]
TELEGRAM_CHAT_IDS = ["663483538"]

TOP_N = 25
MAX_SELECCION_DIARIA = 35


def enviar_telegram(texto):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    trozos = [texto[i:i + 3800] for i in range(0, len(texto), 3800)] or [texto]
    for chat_id in TELEGRAM_CHAT_IDS:
        for trozo in trozos:
            try:
                requests.post(url, data={"chat_id": chat_id, "text": trozo}, timeout=15)
            except Exception as e:
                print(f"Error enviando a Telegram primer set (chat {chat_id}): {e}")


# --- Puente a Supabase (tablas propias, ver docstring del modulo) ---

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")


def _supabase_headers(prefer=None):
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    return headers


def _supabase_habilitado():
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        print(" (aviso: SUPABASE_URL o SUPABASE_SERVICE_ROLE_KEY no configurados, se omite guardado en Supabase)")
        return False
    return True


def guardar_senales_supabase_primer_set(seleccion):
    """Upsert por event_id en la tabla signals_primer_set."""
    if not _supabase_habilitado() or not seleccion:
        return

    filas = []
    for s in seleccion:
        event_id = s.get("event_id")
        if not event_id:
            continue
        filas.append({
            "event_id": str(event_id),
            "liga": s["liga"],
            "home": s["home"],
            "away": s["away"],
            "hora": s["hora"],
            "hora_ts": s["hora_ts"],
            "favorito": s["favorito"],
            "probabilidad": s["probabilidad"],
            "color": s["color"],
            "p_home_individual": s.get("p_home_individual"),
            "p_away_individual": s.get("p_away_individual"),
            "n_h2h": s.get("n_h2h"),
            "racha_home": s.get("racha_home"),
            "racha_away": s.get("racha_away"),
            "tasa_home": s.get("tasa_home"),
            "tasa_away": s.get("tasa_away"),
            "h2h_ultima_fecha": s.get("h2h_ultima_fecha"),
        })

    if not filas:
        return

    try:
        resp = requests.post(
            f"{SUPABASE_URL}/rest/v1/signals_primer_set",
            headers=_supabase_headers(prefer="resolution=merge-duplicates"),
            params={"on_conflict": "event_id"},
            json=filas,
            timeout=20,
        )
        if resp.status_code >= 300:
            print(f" (aviso: Supabase respondio {resp.status_code} al guardar señales primer set: {resp.text[:300]})")
        else:
            print(f" Guardadas {len(filas)} señales primer set en Supabase.")
    except requests.exceptions.RequestException as e:
        print(f" (aviso: error de red guardando señales primer set en Supabase: {e})")


def guardar_estadisticas_supabase_primer_set(estadisticas):
    if not _supabase_habilitado() or not estadisticas:
        return

    fila = {
        "fecha": estadisticas.get("fecha") or datetime.date.today().isoformat(),
        "ganadoras": estadisticas.get("ganadoras", 0),
        "perdidas": estadisticas.get("perdidas", 0),
    }

    try:
        resp = requests.post(
            f"{SUPABASE_URL}/rest/v1/daily_stats_primer_set",
            headers=_supabase_headers(prefer="resolution=merge-duplicates"),
            params={"on_conflict": "fecha"},
            json=[fila],
            timeout=20,
        )
        if resp.status_code >= 300:
            print(f" (aviso: Supabase respondio {resp.status_code} al guardar estadisticas primer set: {resp.text[:300]})")
    except requests.exceptions.RequestException as e:
        print(f" (aviso: error de red guardando estadisticas primer set en Supabase: {e})")


def guardar_resultado_supabase_primer_set(resultado):
    if not _supabase_habilitado() or not resultado:
        return

    event_id = resultado.get("event_id")
    if not event_id:
        return

    fila = {
        "event_id": str(event_id),
        "liga": resultado.get("liga"),
        "home": resultado.get("home"),
        "away": resultado.get("away"),
        "acierto": bool(resultado.get("acierto")),
        "favorito": resultado.get("favorito"),
        "probabilidad": resultado.get("probabilidad"),
        "color": resultado.get("color"),
        "hora_ts": resultado.get("hora_ts"),
        # Marcador en PUNTOS del primer set (no cantidad de sets del partido).
        "sets_home": resultado.get("sets_home"),
        "sets_away": resultado.get("sets_away"),
        "fecha": resultado.get("fecha"),
    }

    try:
        resp = requests.post(
            f"{SUPABASE_URL}/rest/v1/resultados_primer_set",
            headers=_supabase_headers(prefer="resolution=merge-duplicates"),
            params={"on_conflict": "event_id"},
            json=[fila],
            timeout=20,
        )
        if resp.status_code >= 300:
            print(f" (aviso: Supabase respondio {resp.status_code} al guardar resultado primer set: {resp.text[:300]})")
    except requests.exceptions.RequestException as e:
        print(f" (aviso: error de red guardando resultado primer set en Supabase: {e})")


# --- Archivos de estado propios de esta señal (independientes de senales_reales.py) ---

ARCHIVO_PENDIENTES = "predicciones_pendientes_primer_set.json"
ARCHIVO_RESULTADOS_NOTIFICADOS = "resultados_notificados_primer_set.json"
ARCHIVO_ESTADISTICAS = "estadisticas_primer_set.json"
ARCHIVO_AVISOS = "avisos_enviados_primer_set.json"
ARCHIVO_ACTUALIZACIONES = "ultima_actualizacion_primer_set.json"
ARCHIVO_RESUMEN_DIARIO = "resumen_diario_enviado_primer_set.json"
ARCHIVO_SELECCION_DIARIA = "seleccion_diaria_primer_set.json"


def _cargar_json(ruta, valor_por_defecto):
    import json
    if not os.path.exists(ruta):
        return valor_por_defecto() if callable(valor_por_defecto) else valor_por_defecto
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return valor_por_defecto() if callable(valor_por_defecto) else valor_por_defecto


def _guardar_json(ruta, datos, indent=None):
    import json
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=indent)


def cargar_pendientes():
    return _cargar_json(ARCHIVO_PENDIENTES, dict)


def guardar_pendientes(pendientes):
    _guardar_json(ARCHIVO_PENDIENTES, pendientes, indent=2)


def cargar_resultados_notificados():
    return _cargar_json(ARCHIVO_RESULTADOS_NOTIFICADOS, dict)


def guardar_resultados_notificados(datos):
    _guardar_json(ARCHIVO_RESULTADOS_NOTIFICADOS, datos)


def cargar_estadisticas():
    hoy = datetime.date.today().isoformat()
    datos = _cargar_json(ARCHIVO_ESTADISTICAS, lambda: {"fecha": hoy, "ganadoras": 0, "perdidas": 0})
    if datos.get("fecha") != hoy:
        return {"fecha": hoy, "ganadoras": 0, "perdidas": 0}
    return datos


def guardar_estadisticas(datos):
    _guardar_json(ARCHIVO_ESTADISTICAS, datos)


def cargar_avisos():
    return _cargar_json(ARCHIVO_AVISOS, dict)


def guardar_avisos(avisos):
    _guardar_json(ARCHIVO_AVISOS, avisos)


def cargar_actualizaciones():
    return _cargar_json(ARCHIVO_ACTUALIZACIONES, dict)


def guardar_actualizaciones(datos):
    _guardar_json(ARCHIVO_ACTUALIZACIONES, datos)


def cargar_resumen_diario_estado():
    return _cargar_json(ARCHIVO_RESUMEN_DIARIO, dict)


def guardar_resumen_diario_estado(datos):
    _guardar_json(ARCHIVO_RESUMEN_DIARIO, datos)


def cargar_seleccion_diaria():
    hoy = datetime.datetime.now(MADRID_TZ).strftime("%Y-%m-%d")
    datos = _cargar_json(ARCHIVO_SELECCION_DIARIA, lambda: {"fecha": hoy, "event_ids": []})
    if datos.get("fecha") != hoy:
        return {"fecha": hoy, "event_ids": []}
    return datos


def guardar_seleccion_diaria(datos):
    _guardar_json(ARCHIVO_SELECCION_DIARIA, datos)


# --- Probabilidad de ganar el PRIMER set (en vez de "al menos un set" como en senales_reales.py) ---

def jugador_gano_primer_set(jugador, partido):
    """True/False/None (None = ese partido no trae marcador de sets)."""
    sets = partido.get("sets")
    if not sets or len(sets) < 1:
        return None
    resultado = resultado_set(*sets[0])
    if partido["jugador_a"] == jugador:
        return resultado == "a"
    if partido["jugador_b"] == jugador:
        return resultado == "b"
    return None


def partidos_con_set1(jugador, partidos):
    return [p for p in partidos_de_jugador(jugador, partidos) if p.get("sets") and len(p["sets"]) >= 1]


def prob_jugador_gana_primer_set(jugador, oponente, partidos):
    """Misma idea que prob_jugador_gana_set() de senales_reales.py (suavizado +
    ponderado por H2H directo), pero el evento que mide es "ganó el set 1",
    no "ganó al menos un set del partido"."""
    juegos = partidos_con_set1(jugador, partidos)
    n = len(juegos)
    eventos = sum(1 for p in juegos if jugador_gano_primer_set(jugador, p))
    base = prop_suavizada(eventos, n)

    enfrentamientos = [
        p for p in partidos
        if {p["jugador_a"], p["jugador_b"]} == {jugador, oponente} and p.get("sets") and len(p["sets"]) >= 1
    ]
    nh = len(enfrentamientos)
    if nh == 0:
        return base, n, nh
    eventos_h2h = sum(1 for p in enfrentamientos if jugador_gano_primer_set(jugador, p))
    p_h2h = prop_suavizada(eventos_h2h, nh)
    w = peso_h2h(nh)
    return w * p_h2h + (1 - w) * base, n, nh


def calcular_tasa_gana_set1(jugador, partidos):
    juegos = partidos_con_set1(jugador, partidos)
    if not juegos:
        return 0.0
    return sum(1 for p in juegos if jugador_gano_primer_set(jugador, p)) / len(juegos)


def calcular_racha_set1(jugador, partidos):
    juegos = sorted(partidos_con_set1(jugador, partidos), key=lambda p: p["time"])
    racha = 0
    for p in reversed(juegos):
        gano = jugador_gano_primer_set(jugador, p)
        if racha == 0:
            racha = 1 if gano else -1
        elif (racha > 0 and gano) or (racha < 0 and not gano):
            racha += 1 if gano else -1
        else:
            break
    return racha


def main():
    print("Cargando historico acumulado guardado (compartido con senales_reales.py)...")
    historico_guardado = cargar_historico()
    todos_partidos = list(historico_guardado.values())
    print(f"Total partidos historicos disponibles: {len(todos_partidos)}")

    print("\nBuscando proximos partidos...")
    candidatas = []
    busquedas_directas_restantes = MAX_BUSQUEDAS_DIRECTAS_POR_EJECUCION
    for nombre_liga, league_id in LIGAS.items():
        proximos = obtener_partidos_proximos(league_id, paginas=6)

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

            n_home = len(partidos_con_set1(home, todos_partidos))
            n_away = len(partidos_con_set1(away, todos_partidos))
            if (n_home < 15 or n_away < 15) and busquedas_directas_restantes > 0:
                home_id = ev.get("home", {}).get("id")
                away_id = ev.get("away", {}).get("id")
                if n_home < 15 and home_id and busquedas_directas_restantes > 0:
                    completar_historico_jugador(home_id, home, historico_guardado, todos_partidos)
                    busquedas_directas_restantes -= 1
                if n_away < 15 and away_id and busquedas_directas_restantes > 0:
                    completar_historico_jugador(away_id, away, historico_guardado, todos_partidos)
                    busquedas_directas_restantes -= 1
                n_home = len(partidos_con_set1(home, todos_partidos))
                n_away = len(partidos_con_set1(away, todos_partidos))
            if n_home < 15 or n_away < 15:
                continue

            p_home, _, nh = prob_jugador_gana_primer_set(home, away, todos_partidos)
            p_away, _, _ = prob_jugador_gana_primer_set(away, home, todos_partidos)

            if p_home >= p_away:
                favorito, prob_favorito = home, p_home
            else:
                favorito, prob_favorito = away, p_away

            color = color_semaforo(prob_favorito)
            # Señal de primer set: se emite si la probabilidad del
            # favorito es >=70% (tramos VERDE y AMARILLO de
            # color_semaforo). ROJO (65-70%) queda descartado aunque
            # color_semaforo() lo admita, porque para esta señal en
            # particular seguimos queriendo un piso de confianza algo
            # mas alto que el 65% de la señal original.
            if color not in ("VERDE", "AMARILLO"):
                continue

            h2h_info = h2h_detalle(home, away, todos_partidos)

            score = (
                prob_favorito
                + (0.05 * min(nh, 20) / 20)
                + (0.03 * abs(p_home - p_away))
            )

            candidatas.append({
                "liga": nombre_liga, "home": home, "away": away,
                "favorito": favorito, "probabilidad": prob_favorito,
                "score": score, "color": color, "n_h2h": nh,
                "p_home_individual": p_home, "p_away_individual": p_away,
                "hora": hora, "event_id": event_id, "hora_ts": hora_ts,
                "racha_home": calcular_racha_set1(home, todos_partidos),
                "racha_away": calcular_racha_set1(away, todos_partidos),
                "tasa_home": calcular_tasa_gana_set1(home, todos_partidos),
                "tasa_away": calcular_tasa_gana_set1(away, todos_partidos),
                "h2h_ultima_fecha": h2h_info["ultima_fecha"],
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

    print(f"\n{'=' * 70}")
    print(f"SELECCION PRIMER SET DE HOY: {len(ids_bloqueados_hoy)}/{MAX_SELECCION_DIARIA} partidos bloqueados "
          f"(de {len(candidatas)} candidatas esta ejecucion, umbral >=70%)")
    print(f"{'=' * 70}")
    simbolo = {"VERDE": "🟢", "AMARILLO": "🟡", "ROJO": "🔴"}
    for s in seleccion:
        print(f"{simbolo[s['color']]} {s['hora']} {s['liga']:18s} {s['home']:20s} vs {s['away']:20s} | "
              f"{s['favorito']} gana el 1er set: {s['probabilidad'] * 100:5.1f}% (H2H n={s['n_h2h']})")

    if not seleccion:
        print("No se encontraron señales sobre el umbral con los partidos próximos disponibles ahora mismo.")

    guardar_senales_supabase_primer_set(seleccion)

    return seleccion


def formatear_mensaje_individual(s, ahora=None):
    emoji_color = {"VERDE": "🟢", "AMARILLO": "🟡", "ROJO": "🔴"}
    etiqueta_color = {"VERDE": "💪 FUERTE", "AMARILLO": "⭐ ELITE", "ROJO": "🔸 SEÑAL"}
    aviso_home = " ⚠️" if s['racha_home'] <= -3 else ""
    aviso_away = " ⚠️" if s['racha_away'] <= -3 else ""
    fecha_h2h = s['h2h_ultima_fecha'] or "sin enfrentamientos previos"

    if ahora is not None:
        restante_min = max(0, round((s['hora_ts'] - ahora) / 60))
        texto_cuenta = "empieza en menos de 1 min" if restante_min <= 1 else f"empieza en {restante_min} min"
    else:
        texto_cuenta = "empieza en 1h"
    lineas = [
        f"{emoji_color[s['color']]} {s['liga']} | {etiqueta_color[s['color']]} | ⏳ {texto_cuenta}",
        f"🕐 {s['hora']} · {s['home']} vs {s['away']}",
        f"🏓 GANA EL 1ER SET: {s['favorito'].upper()} ({s['probabilidad'] * 100:.1f}%)",
        f"📊 Prob. individual set 1: {s['home']} {s['p_home_individual'] * 100:.1f}% · {s['away']} {s['p_away_individual'] * 100:.1f}%",
        f"🔥 Racha set 1: {s['home']} {s['racha_home']:+d}{aviso_home} · {s['away']} {s['racha_away']:+d}{aviso_away}",
        f"🏆 Tasa gana set 1: {s['home']} {s['tasa_home'] * 100:.0f}% · {s['away']} {s['tasa_away'] * 100:.0f}%",
        f"🤝 H2H: {s['n_h2h']} partidos (ultimo: {fecha_h2h})",
    ]
    return "\n".join(lineas)


def formatear_mensaje_actualizacion(s, prob_anterior):
    emoji_color = {"VERDE": "🟢", "AMARILLO": "🟡", "ROJO": "🔴"}
    diferencia = (s["probabilidad"] - prob_anterior) * 100
    flecha = "📈" if diferencia > 0 else ("📉" if diferencia < 0 else "➡️")
    fecha_h2h = s['h2h_ultima_fecha'] or "sin enfrentamientos previos"

    lineas = [
        f"🔄 ACTUALIZACIÓN | {emoji_color[s['color']]} {s['liga']}",
        f"🕐 {s['hora']} · {s['home']} vs {s['away']}",
        f"🏓 GANA EL 1ER SET: {s['favorito'].upper()} ({s['probabilidad'] * 100:.1f}% {flecha} {diferencia:+.1f} pts desde el ultimo aviso)",
        f"🔥 Racha set 1: {s['home']} {s['racha_home']:+d} · {s['away']} {s['racha_away']:+d}",
        f"🤝 H2H: {s['n_h2h']} partidos (ultimo: {fecha_h2h})",
    ]
    return "\n".join(lineas)


def comprobar_predicciones_anteriores():
    pendientes = cargar_pendientes()
    if not pendientes:
        return
    print(f" (DIAG resultado primer set: comprobando {len(pendientes)} predicciones pendientes)")
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
        if resultado is None or not resultado.get("sets") or len(resultado["sets"]) < 1:
            print(f" (DIAG resultado primer set {event_id}: sin marcador de set 1 disponible, se descarta "
                  f"la señal sin guardar resultado; ss={detalle.get('ss')!r})")
            continue

        gano_home_set1 = resultado_set(*resultado["sets"][0]) == "a"
        ganador_set1 = resultado["jugador_a"] if gano_home_set1 else resultado["jugador_b"]
        acerto = ganador_set1 == pred["favorito"]
        marcador_set1 = resultado["sets"][0]

        if acerto:
            estadisticas["ganadoras"] += 1
            mensaje = (
                f"GANADA ✅\n"
                f"{pred['liga'].upper()}: {pred['home'].upper()} VS {pred['away'].upper()}\n"
                f"{pred['favorito'].upper()} SE LLEVÓ EL PRIMER SET ({marcador_set1[0]}-{marcador_set1[1]})\n"
                f"📊 Hoy: {estadisticas['ganadoras']} verdes / {estadisticas['perdidas']} rojas"
            )
        else:
            estadisticas["perdidas"] += 1
            mensaje = (
                f"PERDIDA ❌😢\n"
                f"{pred['liga'].upper()}: {pred['home'].upper()} VS {pred['away'].upper()}\n"
                f"PRIMER SET FUE PARA {ganador_set1.upper()} ({marcador_set1[0]}-{marcador_set1[1]}), "
                f"no {pred['favorito'].upper()}\n"
                f"📊 Hoy: {estadisticas['ganadoras']} verdes / {estadisticas['perdidas']} rojas"
            )
        enviar_telegram(mensaje)
        notificados[event_id] = True

        fecha_partido = (
            datetime.datetime.fromtimestamp(pred["hora_ts"], tz=MADRID_TZ).strftime("%Y-%m-%d")
            if pred.get("hora_ts")
            else datetime.date.today().isoformat()
        )
        guardar_resultado_supabase_primer_set({
            "event_id": event_id,
            "liga": pred.get("liga"),
            "home": pred.get("home"),
            "away": pred.get("away"),
            "acierto": acerto,
            "favorito": pred.get("favorito"),
            "probabilidad": pred.get("probabilidad"),
            "color": pred.get("color"),
            "hora_ts": pred.get("hora_ts"),
            "sets_home": marcador_set1[0],
            "sets_away": marcador_set1[1],
            "fecha": fecha_partido,
        })

    resueltas = len(pendientes) - len(aun_pendientes)
    print(f" (DIAG resultado primer set: {resueltas} resueltas en esta ejecucion, {len(aun_pendientes)} siguen pendientes)")
    guardar_pendientes(aun_pendientes)
    guardar_resultados_notificados(notificados)
    guardar_estadisticas(estadisticas)
    guardar_estadisticas_supabase_primer_set(estadisticas)


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

    print(f"Avisos individuales primer set enviados en esta ejecucion: {enviados_ahora}")
    return enviados_ahora


def enviar_actualizaciones_periodicas(seleccion):
    actualizaciones = cargar_actualizaciones()
    ahora = time.time()
    ventana_actualizacion = 3600
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

    print(f"Actualizaciones periodicas primer set enviadas en esta ejecucion: {enviadas}")
    return enviadas


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
        lineas = [f"📋 RESUMEN DEL DIA (1ER SET) — {hoy}", f"Mejores pronosticos de hoy ({len(proximas)}):", ""]
        for s in proximas:
            lineas.append(
                f"{simbolo[s['color']]} {s['hora']} {s['liga']} {s['home']} vs {s['away']} | "
                f"{s['favorito']} gana el 1er set: {s['probabilidad'] * 100:.1f}%"
            )
        mensaje = "\n".join(lineas)
    else:
        mensaje = f"📋 RESUMEN DEL DIA (1ER SET) — {hoy}\nNo hay señales sobre el umbral con los partidos disponibles ahora mismo."

    enviar_telegram(mensaje)
    estado["ultima_fecha"] = hoy
    guardar_resumen_diario_estado(estado)
    return True


if __name__ == "__main__":
    import sys
    import os as os_lock

    ARCHIVO_CANDADO = "ejecucion_en_curso_primer_set.lock"

    if os_lock.path.exists(ARCHIVO_CANDADO):
        edad_candado = time.time() - os_lock.path.getmtime(ARCHIVO_CANDADO)
        if edad_candado < 900:
            print("Ya hay una ejecucion de primer set en curso, se cancela esta para evitar duplicados.")
            sys.exit(0)

    with open(ARCHIVO_CANDADO, "w", encoding="utf-8") as f:
        f.write(str(time.time()))

    try:
        comprobar_predicciones_anteriores()

        seleccion_hoy = main()

        if seleccion_hoy:
            pendientes = cargar_pendientes()
            notificados = cargar_resultados_notificados()
            for s in seleccion_hoy:
                eid = s.get("event_id")
                if eid and str(eid) not in notificados:
                    pendientes[str(eid)] = s
            guardar_pendientes(pendientes)

        enviar_avisos_pendientes(seleccion_hoy)
        enviar_actualizaciones_periodicas(seleccion_hoy)
        enviar_resumen_diario(seleccion_hoy)
    finally:
        if os_lock.path.exists(ARCHIVO_CANDADO):
            os_lock.remove(ARCHIVO_CANDADO)
