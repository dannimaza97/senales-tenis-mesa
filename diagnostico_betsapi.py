"""Diagnóstico persistente de BetsAPI, sin publicar tokens ni URLs con credenciales."""
import datetime
import json
import os
import requests

BASE = "https://api.b365api.com/v1/events/upcoming"
LIGAS = {"TT Elite Series": 29128, "Setka Cup": 22307, "Czech Liga Pro": 22742, "TT Cup": 29097}
DESTINO = "estado_betsapi.json"
DESTINO_PARTIDOS = "proximos_partidos.json"


def main():
    token = os.environ.get("BETSAPI_TOKEN")
    estado = {
        "fecha_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "token_configurado": bool(token),
        "ligas": {},
    }
    partidos_futuros = []
    ahora_ts = datetime.datetime.now(datetime.timezone.utc).timestamp()
    if not token:
        print("ERROR: BETSAPI_TOKEN no configurado")
    for nombre, league_id in LIGAS.items():
        if not token:
            estado["ligas"][nombre] = {"estado": "sin_token", "partidos": 0}
            continue
        try:
            respuesta = requests.get(
                BASE,
                params={"token": token, "sport_id": 92, "league_id": league_id, "page": 1},
                timeout=20,
            )
            datos = respuesta.json()
            resultados = datos.get("results")
            cantidad = len(resultados) if isinstance(resultados, list) else 0
            if isinstance(resultados, list):
                for evento in resultados:
                    try:
                        ts = int(evento.get("time"))
                        if ts <= ahora_ts or ts > ahora_ts + 48 * 3600:
                            continue
                        home = str((evento.get("home") or {}).get("name") or "")[:120]
                        away = str((evento.get("away") or {}).get("name") or "")[:120]
                        if home and away:
                            partidos_futuros.append({
                                "event_id": str(evento.get("id") or "")[:30],
                                "liga": nombre,
                                "home": home,
                                "away": away,
                                "hora_utc": datetime.datetime.fromtimestamp(
                                    ts, datetime.timezone.utc
                                ).isoformat(),
                            })
                    except (TypeError, ValueError, OverflowError):
                        continue
            ok = respuesta.ok and str(datos.get("success")).lower() in ("1", "true")
            estado["ligas"][nombre] = {
                "estado": "ok" if ok else "error_api",
                "http": respuesta.status_code,
                "partidos": cantidad,
                "codigo_error": str(datos.get("error_code", ""))[:30] if not ok else "",
            }
            print(f"{nombre}: HTTP={respuesta.status_code}, API={'OK' if ok else 'ERROR'}, partidos={cantidad}")
        except (requests.RequestException, ValueError) as exc:
            estado["ligas"][nombre] = {"estado": "error_conexion", "partidos": 0}
            print(f"{nombre}: error de conexión ({type(exc).__name__})")
    with open(DESTINO, "w", encoding="utf-8") as salida:
        json.dump(estado, salida, ensure_ascii=False, indent=2)
        salida.write("\n")
    partidos_futuros.sort(key=lambda x: x["hora_utc"])
    with open(DESTINO_PARTIDOS, "w", encoding="utf-8") as salida:
        json.dump({
            "fecha_utc": estado["fecha_utc"],
            "origen": "BetsAPI upcoming, primera pagina por liga",
            "nota": "Partidos sin prediccion ni recomendacion",
            "partidos": partidos_futuros,
        }, salida, ensure_ascii=False, indent=2)
        salida.write("\\n")
    print(f"Diagnostico guardado; proximos partidos: {len(partidos_futuros)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
