import unittest
from datetime import datetime, timezone, timedelta
from pulsopro2.core import validar_partido, validar_probabilidad, metricas_calibracion
from pulsopro2.historial import guardar_partidos_finalizados

AHORA = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)

class TestValidacion(unittest.TestCase):
    def evento(self, **cambios):
        e = {"id": "42", "time": int((AHORA + timedelta(hours=1)).timestamp()),
             "home": {"name": "A"}, "away": {"name": "B"}}
        e.update(cambios)
        return e

    def test_partido_futuro(self):
        self.assertEqual(validar_partido(self.evento(), AHORA)["event_id"], "42")

    def test_rechaza_pasado(self):
        self.assertIsNone(validar_partido(self.evento(time=int(AHORA.timestamp()) - 1), AHORA))

    def test_rechaza_mismo_jugador(self):
        self.assertIsNone(validar_partido(self.evento(away={"name": "a"}), AHORA))

    def test_rechaza_incompleto(self):
        self.assertIsNone(validar_partido({"id": 1}, AHORA))

    def test_rechaza_muy_lejano(self):
        self.assertIsNone(validar_partido(self.evento(time=int((AHORA + timedelta(days=3)).timestamp())), AHORA))

    def test_probabilidades_invalidas(self):
        for x in (-0.1, 1.1, float("nan"), float("inf"), True):
            with self.assertRaises(ValueError):
                validar_probabilidad(x)

class TestCalibracion(unittest.TestCase):
    def test_vacio(self):
        self.assertEqual(metricas_calibracion([])["n"], 0)

    def test_brier_perfecto(self):
        m = metricas_calibracion([(1, 1), (0, 0)])
        self.assertEqual(m["brier"], 0)
        self.assertEqual(m["n"], 2)

    def test_brier_incorrecto(self):
        self.assertEqual(metricas_calibracion([(1, 0)])["brier"], 1)

    def test_bandas(self):
        m = metricas_calibracion([(0.8, 1), (0.8, 0)])
        self.assertEqual(m["bandas"][0]["frecuencia_real"], 0.5)

class SesionFalsa:
    def __init__(self): self.calls = []
    def post(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self
    def raise_for_status(self): return None

class TestHistorial(unittest.TestCase):
    def test_upsert_idempotente_por_lote(self):
        sesion = SesionFalsa()
        fila = {"event_id": "1", "liga": "TT Elite", "home": "A", "away": "B",
                "hora_ts": 100, "sets_home": 3, "sets_away": 1}
        self.assertEqual(guardar_partidos_finalizados([fila, fila], url="https://test.supabase.co",
                           clave="falsa", sesion=sesion), 1)
        self.assertEqual(len(sesion.calls), 1)
        self.assertEqual(len(sesion.calls[0][1]["json"]), 1)

    def test_rechaza_marcador_invalido(self):
        sesion = SesionFalsa()
        fila = {"event_id": "1", "liga": "TT", "home": "A", "away": "B",
                "hora_ts": 100, "sets_home": 2, "sets_away": 2}
        self.assertEqual(guardar_partidos_finalizados([fila], url="https://test.supabase.co",
                           clave="falsa", sesion=sesion), 0)

if __name__ == "__main__":
    unittest.main()
