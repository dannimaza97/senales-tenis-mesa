"""Diagnóstico persistente de BetsAPI, sin publicar tokens ni URLs con credenciales."""
import datetime
import json
import os
import requests

BASE = "https://api.b365api.com/v1/events/upcoming"
LIGAS = {"TT Elite Series": 29128, "Setka Cup": 22307, "Czech Liga Pro": 22742, "TT Cup": 29097}
DESTINO = "estado_betsapi.json"


def main():
    token = os.environ.get("BETSAPI_TOKEN")
    estado = {
        "fecha_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "token_configurado": bool(token),
        "ligas": {},
    }
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
    print(f"Diagnóstico guardado en {DESTINO}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
