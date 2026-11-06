"""Comprueba la frescura de la última publicación de señales sin exponer credenciales."""
import argparse
import datetime as dt
import json
from pathlib import Path


def comprobar_estado(ruta, ahora=None, max_minutos=45):
    ahora = ahora or dt.datetime.now(dt.timezone.utc)
    if ahora.tzinfo is None:
        raise ValueError("ahora debe incluir zona horaria")
    if max_minutos <= 0:
        raise ValueError("max_minutos debe ser positivo")
    try:
        estado = json.loads(Path(ruta).read_text(encoding="utf-8"))
        fecha = dt.datetime.fromisoformat(estado["fecha_utc"].replace("Z", "+00:00"))
        if fecha.tzinfo is None:
            return {"ok": False, "motivo": "fecha_sin_zona"}
        edad = (ahora - fecha).total_seconds() / 60
        if edad < -5:
            return {"ok": False, "motivo": "fecha_futura"}
        if estado.get("estado") != "ok" or estado.get("http") not in (200, 201, 204):
            return {"ok": False, "motivo": "ultima_publicacion_no_confirmada", "edad_minutos": round(edad, 1)}
        if edad > max_minutos:
            return {"ok": False, "motivo": "publicacion_desactualizada", "edad_minutos": round(edad, 1)}
        return {"ok": True, "motivo": "publicacion_reciente", "edad_minutos": round(edad, 1)}
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return {"ok": False, "motivo": "diagnostico_ausente_o_invalido"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--archivo", default="estado_publicacion_supabase.json")
    parser.add_argument("--max-minutos", type=int, default=45)
    args = parser.parse_args()
    resultado = comprobar_estado(args.archivo, max_minutos=args.max_minutos)
    print(json.dumps(resultado, ensure_ascii=False))
    raise SystemExit(0 if resultado["ok"] else 1)
