"""PulsoPro 2: validacion y evaluacion sin apuestas ni datos inventados."""
from datetime import datetime, timezone
from math import log
from zoneinfo import ZoneInfo

MADRID = ZoneInfo("Europe/Madrid")

def validar_partido(evento, ahora=None):
    """Normaliza un evento BetsAPI; rechaza eventos pasados o incompletos."""
    ahora = ahora or datetime.now(timezone.utc)
    if ahora.tzinfo is None:
        raise ValueError("ahora debe tener zona horaria")
    try:
        ts = int(evento["time"])
        home = str(evento["home"]["name"]).strip()
        away = str(evento["away"]["name"]).strip()
        eid = str(evento["id"]).strip()
        if not eid or not home or not away or home.casefold() == away.casefold():
            return None
        inicio = datetime.fromtimestamp(ts, timezone.utc)
        if inicio <= ahora or (inicio - ahora).total_seconds() > 48 * 3600:
            return None
        return {"event_id": eid, "home": home, "away": away,
                "hora_ts": ts, "hora_madrid": inicio.astimezone(MADRID).isoformat()}
    except (KeyError, TypeError, ValueError, OverflowError, AttributeError):
        return None

def validar_probabilidad(valor):
    """Una probabilidad solo es valida si es finita y pertenece a [0, 1]."""
    from math import isfinite
    if isinstance(valor, bool) or not isinstance(valor, (float, int)):
        raise ValueError("probabilidad no numerica")
    if not isfinite(valor) or not 0 <= valor <= 1:
        raise ValueError("probabilidad fuera de rango")
    return float(valor)

def metricas_calibracion(registros, intervalos=10):
    """Registros: (probabilidad predicha ANTES del partido, resultado 0/1).
    Brier y log-loss; bandas de calibracion, sin entrenar con los resultados.
    """
    if not registros:
        return {"n": 0, "brier": None, "log_loss": None, "bandas": []}
    suma_brier = suma_log = 0.0
    bandas = [[] for _ in range(intervalos)]
    for prob, resultado in registros:
        p = validar_probabilidad(prob)
        if resultado not in (0, 1) or isinstance(resultado, bool):
            raise ValueError("resultado debe ser 0 o 1")
        suma_brier += (p - resultado) ** 2
        p_segura = min(1 - 1e-15, max(1e-15, p))
        suma_log -= resultado * log(p_segura) + (1 - resultado) * log(1 - p_segura)
        bandas[min(intervalos - 1, int(p * intervalos))].append((p, resultado))
    return {
        "n": len(registros),
        "brier": suma_brier / len(registros),
        "log_loss": suma_log / len(registros),
        "bandas": [
            {"desde": i / intervalos, "hasta": (i + 1) / intervalos,
             "n": len(b), "prediccion_media": sum(p for p, _ in b) / len(b),
             "frecuencia_real": sum(y for _, y in b) / len(b)}
            for i, b in enumerate(bandas) if b
        ],
    }
