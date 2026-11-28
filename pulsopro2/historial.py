"""Almacenamiento persistente de partidos finalizados en Supabase REST.
La clave service_role nunca debe exponerse en el frontend ni en logs.
"""
import os
import requests

def guardar_partidos_finalizados(partidos, *, url=None, clave=None, sesion=None):
    url = (url if url is not None else os.getenv("SUPABASE_URL", "")).rstrip("/")
    clave = clave if clave is not None else os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url.startswith("https://") or not clave:
        raise RuntimeError("Falta configuracion segura de Supabase")
    filas = []
    vistos = set()
    for partido in partidos:
        try:
            eid = str(partido["event_id"]).strip()
            ts = int(partido["hora_ts"])
            sets_home, sets_away = int(partido["sets_home"]), int(partido["sets_away"])
            if not eid or ts <= 0 or min(sets_home, sets_away) < 0:
                continue
            if max(sets_home, sets_away) != 3 or min(sets_home, sets_away) >= 3:
                continue
            if eid in vistos:
                continue
            vistos.add(eid)
            filas.append({"event_id": eid, "liga": str(partido["liga"]),
                          "home": str(partido["home"]), "away": str(partido["away"]),
                          "hora_ts": ts, "sets_home": sets_home,
                          "sets_away": sets_away})
        except (KeyError, TypeError, ValueError):
            continue
    if not filas:
        return 0
    cliente = sesion or requests
    # Lotes pequenos: PostgREST y red no deben recibir un cuerpo gigante.
    headers = {"apikey": clave, "Authorization": "Bearer " + clave,
               "Content-Type": "application/json",
               "Prefer": "resolution=merge-duplicates,return=minimal"}
    for inicio in range(0, len(filas), 200):
        resp = cliente.post(url + "/rest/v1/pulsopro2_partidos",
                           params={"on_conflict": "event_id"},
                           headers=headers, json=filas[inicio:inicio + 200], timeout=20)
        resp.raise_for_status()
    return len(filas)
