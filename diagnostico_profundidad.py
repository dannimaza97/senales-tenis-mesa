"""
Diagnostico de profundidad de paginas disponibles en el plan de BetsAPI.
Recorre /events/ended pagina por pagina para cada liga y muestra en que
pagina la API deja de devolver resultados. Con esto decidimos si el limite
actual de 150 paginas por liga se puede subir. Este script es temporal:
se borra (junto con el paso en senales.yml) en cuanto tengamos el resultado.
"""

import time
import requests

from senales_reales import BASE_URL, TOKEN, SPORT_ID_TENIS_MESA, LIGAS

MAX_PAGINAS = 200  # un poco por encima del limite actual (150) para ver si hay margen


def diagnosticar_liga(nombre_liga, league_id):
    print(f"\n=== {nombre_liga} (league_id={league_id}) ===")
    ultima_pagina_con_datos = 0
    total_partidos = 0
    llego_al_tope_de_prueba = True
    for page in range(1, MAX_PAGINAS + 1):
        try:
            resp = requests.get(f"{BASE_URL}/events/ended", params={
                "token": TOKEN, "sport_id": SPORT_ID_TENIS_MESA,
                "league_id": league_id, "page": page,
            }, timeout=15)
        except requests.exceptions.RequestException as e:
            print(f"  Pagina {page}: error de red ({e}), me detengo aqui.")
            llego_al_tope_de_prueba = False
            break

        try:
            data = resp.json()
        except ValueError:
            print(f"  Pagina {page}: respuesta no valida (HTTP {resp.status_code}), me detengo aqui.")
            llego_al_tope_de_prueba = False
            break

        resultados = data.get("results") or []
        if not data.get("success") or not resultados:
            print(f"  Pagina {page}: sin resultados (success={data.get('success')}). "
                  f"La API dejo de dar datos aqui.")
            llego_al_tope_de_prueba = False
            break

        ultima_pagina_con_datos = page
        total_partidos += len(resultados)
        time.sleep(0.15)

    if llego_al_tope_de_prueba:
        print(f"  Se llego al limite de prueba ({MAX_PAGINAS} paginas) y la API SEGUIA devolviendo datos.")

    print(f"  -> Ultima pagina con datos: {ultima_pagina_con_datos}")
    print(f"  -> Total de partidos recogidos: {total_partidos}")
    return ultima_pagina_con_datos, total_partidos


def main():
    print("Diagnostico de profundidad de paginas por liga (BetsAPI /events/ended)")
    resumen = {}
    for nombre_liga, league_id in LIGAS.items():
        ultima_pagina, total = diagnosticar_liga(nombre_liga, league_id)
        resumen[nombre_liga] = (ultima_pagina, total)

    print("\n" + "=" * 60)
    print("RESUMEN")
    print("=" * 60)
    for nombre_liga, (ultima_pagina, total) in resumen.items():
        aviso = " (llego al tope del historico actual de 150!)" if ultima_pagina >= 150 else ""
        print(f"{nombre_liga:20s} -> profundidad real: {ultima_pagina} paginas, {total} partidos{aviso}")


if __name__ == "__main__":
    main()
