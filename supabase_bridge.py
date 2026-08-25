"""
Puente entre el motor de señales (senales_reales.py) y Supabase.

Copia este archivo a la raíz de tu repo "senales-tenis-mesa" (junto a
senales_reales.py) y sigue las instrucciones del README de la web para
enchufarlo. No añade dependencias nuevas: usa `requests`, que el
proyecto ya tiene en requirements.txt.

Variables de entorno necesarias (se configuran como GitHub Secrets,
NUNCA escritas en el código):
  - SUPABASE_URL               (ej. https://tuproyecto.supabase.co)
  - SUPABASE_SERVICE_ROLE_KEY  (Project Settings > API > service_role)

La service_role key se salta las políticas de RLS a propósito: es la
única forma en que este script puede escribir en las tablas `signals`
y `daily_stats`, que están bloqueadas para cualquier otro cliente.
"""

import os
import datetime
import requests

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")


def _headers(prefer=None):
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    return headers


def _habilitado():
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        print(" (aviso: SUPABASE_URL o SUPABASE_SERVICE_ROLE_KEY no configurados, se omite guardado en Supabase)")
        return False
    return True


def guardar_senales_supabase(seleccion):
    """Recibe la misma lista `seleccion` que genera main() en
    senales_reales.py y la sube (upsert por event_id) a la tabla
    `signals` de Supabase."""
    if not _habilitado() or not seleccion:
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
            "probabilidad": s["probabilidad"],
            "color": s["color"],
            "p_home_individual": s.get("p_home_individual"),
            "p_away_individual": s.get("p_away_individual"),
            "n_h2h": s.get("n_h2h"),
            "senal_3_0": s.get("senal_3_0"),
            "senal_4mas": s.get("senal_4mas"),
            "impulso_home": s.get("impulso_home"),
            "impulso_away": s.get("impulso_away"),
            "racha_home": s.get("racha_home"),
            "racha_away": s.get("racha_away"),
            "tasa_home": s.get("tasa_home"),
            "tasa_away": s.get("tasa_away"),
            "barrido_home": s.get("barrido_home"),
            "barrido_away": s.get("barrido_away"),
            "fue_barrido_home": s.get("fue_barrido_home"),
            "fue_barrido_away": s.get("fue_barrido_away"),
            "h2h_ultima_fecha": s.get("h2h_ultima_fecha"),
            "h2h_historial": s.get("h2h_historial"),
            "prob_partido_home": s.get("prob_partido_home"),
            "prob_partido_away": s.get("prob_partido_away"),
            "senal_1_1": s.get("senal_1_1"),
            "senal_3er": s.get("senal_3er"),
            "discrepancia": s.get("discrepancia"),
            "ultimo_torneo": s.get("ultimo_torneo"),
        })

    if not filas:
        return

    try:
        resp = requests.post(
            f"{SUPABASE_URL}/rest/v1/signals",
            headers=_headers(prefer="resolution=merge-duplicates"),
            params={"on_conflict": "event_id"},
            json=filas,
            timeout=20,
        )
        if resp.status_code >= 300:
            print(f" (aviso: Supabase respondio {resp.status_code} al guardar señales: {resp.text[:300]})")
        else:
            print(f" Guardadas {len(filas)} señales en Supabase.")
    except requests.exceptions.RequestException as e:
        print(f" (aviso: error de red guardando señales en Supabase: {e})")


def guardar_estadisticas_supabase(estadisticas):
    """Recibe el dict {"fecha", "ganadoras", "perdidas"} y hace upsert
    en la tabla `daily_stats` de Supabase."""
    if not _habilitado() or not estadisticas:
        return

    fila = {
        "fecha": estadisticas.get("fecha") or datetime.date.today().isoformat(),
        "ganadoras": estadisticas.get("ganadoras", 0),
        "perdidas": estadisticas.get("perdidas", 0),
    }

    try:
        resp = requests.post(
            f"{SUPABASE_URL}/rest/v1/daily_stats",
            headers=_headers(prefer="resolution=merge-duplicates"),
            params={"on_conflict": "fecha"},
            json=[fila],
            timeout=20,
        )
        if resp.status_code >= 300:
            print(f" (aviso: Supabase respondio {resp.status_code} al guardar estadisticas: {resp.text[:300]})")
    except requests.exceptions.RequestException as e:
        print(f" (aviso: error de red guardando estadisticas en Supabase: {e})")


def guardar_resultado_supabase(resultado):
    """Recibe un dict con el resultado ya resuelto de una señal
    (event_id, liga, home, away, acierto, probabilidad, color, hora_ts,
    fecha) y hace upsert (por event_id) en la tabla `resultados` de
    Supabase. Esto alimenta el historial de aciertos por liga y por
    dia que se muestra en la web."""
    if not _habilitado() or not resultado:
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
        "probabilidad": resultado.get("probabilidad"),
        "color": resultado.get("color"),
        "hora_ts": resultado.get("hora_ts"),
        "sets_home": resultado.get("sets_home"),
        "sets_away": resultado.get("sets_away"),
        "fecha": resultado.get("fecha"),
    }

    try:
        resp = requests.post(
            f"{SUPABASE_URL}/rest/v1/resultados",
            headers=_headers(prefer="resolution=merge-duplicates"),
            params={"on_conflict": "event_id"},
            json=[fila],
            timeout=20,
        )
        if resp.status_code >= 300:
            print(f" (aviso: Supabase respondio {resp.status_code} al guardar resultado: {resp.text[:300]})")
    except requests.exceptions.RequestException as e:
        print(f" (aviso: error de red guardando resultado en Supabase: {e})")

def obtener_signals_sin_resultado(horas_atras=72):
    """Red de seguridad para reconciliar señales huerfanas: devuelve las
    filas de la tabla `signals` de las ultimas `horas_atras` horas que
    todavia no tienen una fila correspondiente en `resultados`.

    Existe porque `signals` se escribe por HTTP en cuanto una señal se
    selecciona, sin depender de que el commit de git de esa misma
    ejecucion consiga hacer push (a diferencia de
    predicciones_pendientes.json, que vive solo en el checkout local y
    se pierde si ese push falla, o si el partido ya no aparece en
    events/upcoming de BetsAPI la siguiente vez que main() corre). Por
    eso `signals` es la fuente de verdad mas fiable de "que señales
    existen" para ir a rellenar el resultado que falte."""
    if not _habilitado():
        return []

    ahora = datetime.datetime.now(datetime.timezone.utc)
    desde_ts = int((ahora - datetime.timedelta(hours=horas_atras)).timestamp())

    try:
        resp_signals = requests.get(
            f"{SUPABASE_URL}/rest/v1/signals",
            headers=_headers(),
            params={
                "select": "event_id,liga,home,away,hora,hora_ts,probabilidad,color",
                "hora_ts": f"gte.{desde_ts}",
                "order": "hora_ts.asc",
            },
            timeout=20,
        )
        senales = resp_signals.json() if resp_signals.status_code == 200 else []
    except requests.exceptions.RequestException as e:
        print(f"    (aviso: error de red consultando señales de Supabase para reconciliacion: {e})")
        return []

    if not senales:
        return []

    try:
        resp_resultados = requests.get(
            f"{SUPABASE_URL}/rest/v1/resultados",
            headers=_headers(),
            params={"select": "event_id", "hora_ts": f"gte.{desde_ts}"},
            timeout=20,
        )
        ya_resueltos = {str(r["event_id"]) for r in resp_resultados.json()} if resp_resultados.status_code == 200 else set()
    except requests.exceptions.RequestException as e:
        print(f"    (aviso: error de red consultando resultados de Supabase para reconciliacion: {e})")
        return []

    return [s for s in senales if str(s.get("event_id")) not in ya_resueltos]


def marcar_notificado_supabase(event_id):
    """Registra en Supabase que ya se envio el aviso de Telegram
    (GANADORA/PERDIDA) para este event_id.

    Es la copia duradera de resultados_notificados.json: se escribe por
    HTTP en el momento en que se manda el aviso, sin depender de que el
    commit de git de esa ejecucion consiga hacer push. Sin esto, si ese
    push falla y resultados_notificados.json vuelve a un estado
    anterior en el siguiente checkout, la ejecucion siguiente puede
    volver a mandar el mismo aviso de Telegram por segunda vez (el bug
    de duplicados que ya se vio antes).

    Requiere una tabla `resultados_notificados` en Supabase con columnas
    `event_id text primary key` y `notificado_at timestamptz default
    now()`. Si la tabla todavia no existe, esto simplemente avisa por
    consola y no rompe nada (igual que el resto de integraciones con
    Supabase de este archivo)."""
    if not _habilitado() or not event_id:
        return
    try:
        resp = requests.post(
            f"{SUPABASE_URL}/rest/v1/resultados_notificados",
            headers=_headers(prefer="resolution=merge-duplicates"),
            params={"on_conflict": "event_id"},
            json=[{"event_id": str(event_id)}],
            timeout=20,
        )
        if resp.status_code >= 300:
            print(f" (aviso: Supabase respondio {resp.status_code} al marcar notificado: {resp.text[:300]})")
    except requests.exceptions.RequestException as e:
        print(f" (aviso: error de red marcando notificado en Supabase: {e})")


def obtener_notificados_supabase(horas_atras=72):
    """Devuelve el conjunto de event_id marcados como notificados en
    Supabase en las ultimas `horas_atras` horas.

    Se usa para fusionar con resultados_notificados.json al arrancar
    comprobar_predicciones_anteriores(), de forma que el registro de
    "ya se aviso este resultado por Telegram" sobreviva aunque el
    archivo local se haya reseteado por un push de git fallido."""
    if not _habilitado():
        return set()

    ahora = datetime.datetime.now(datetime.timezone.utc)
    desde = (ahora - datetime.timedelta(hours=horas_atras)).isoformat()

    try:
        resp = requests.get(
            f"{SUPABASE_URL}/rest/v1/resultados_notificados",
            headers=_headers(),
            params={"select": "event_id", "notificado_at": f"gte.{desde}"},
            timeout=20,
        )
        if resp.status_code == 200:
            return {str(r["event_id"]) for r in resp.json()}
        if resp.status_code != 404:
            print(f" (aviso: Supabase respondio {resp.status_code} consultando notificados: {resp.text[:300]})")
    except requests.exceptions.RequestException as e:
        print(f" (aviso: error de red consultando notificados de Supabase: {e})")
    return set()

