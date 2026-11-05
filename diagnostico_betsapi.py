"""Diagnóstico de solo lectura para BetsAPI; no imprime credenciales ni modifica datos."""
import os
import requests

BASE = 'https://api.b365api.com/v1/events/upcoming'
LIGAS = {'TT Elite Series': 29128, 'Setka Cup': 22307, 'Czech Liga Pro': 22742, 'TT Cup': 29097}

def main():
    token = os.environ.get('BETSAPI_TOKEN')
    if not token:
        print('ERROR: BETSAPI_TOKEN no configurado')
        return 1
    for nombre, league_id in LIGAS.items():
        try:
            respuesta = requests.get(BASE, params={'token': token, 'sport_id': 92, 'league_id': league_id, 'page': 1}, timeout=20)
            # Nunca imprimir la URL completa, porque contiene el token.
            datos = respuesta.json()
            resultados = datos.get('results')
            cantidad = len(resultados) if isinstance(resultados, list) else 0
            print(f'{nombre}: HTTP={respuesta.status_code}, success={datos.get("success")!r}, resultados={cantidad}')
            if datos.get('success') not in (1, True):
                print(f'  Respuesta no satisfactoria; revisar plan, permisos y límites de la API. Código={datos.get("error_code", "no indicado")}')
        except (requests.RequestException, ValueError) as exc:
            print(f'{nombre}: fallo de conexión o JSON inválido ({type(exc).__name__})')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
