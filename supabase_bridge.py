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
