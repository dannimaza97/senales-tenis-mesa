import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from pulsopro2.monitor_publicacion import comprobar_estado


class TestMonitorPublicacion(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ruta = Path(self.tmp.name) / "estado.json"
        self.ahora = dt.datetime(2026, 11, 7, 12, 0, tzinfo=dt.timezone.utc)

    def escribir(self, minutos, estado="ok", http=200):
        self.ruta.write_text(json.dumps({
            "fecha_utc": (self.ahora - dt.timedelta(minutes=minutos)).isoformat(),
            "estado": estado, "http": http
        }))

    def test_publicacion_reciente(self):
        self.escribir(20)
        self.assertTrue(comprobar_estado(self.ruta, self.ahora)["ok"])

    def test_publicacion_congelada(self):
        self.escribir(80)
        self.assertEqual(comprobar_estado(self.ruta, self.ahora)["motivo"], "publicacion_desactualizada")

    def test_publicacion_fallida(self):
        self.escribir(5, "error_http", 500)
        self.assertFalse(comprobar_estado(self.ruta, self.ahora)["ok"])

    def test_archivo_ausente(self):
        self.assertEqual(comprobar_estado(self.ruta, self.ahora)["motivo"], "diagnostico_ausente_o_invalido")

    def test_fecha_futura(self):
        self.escribir(-20)
        self.assertEqual(comprobar_estado(self.ruta, self.ahora)["motivo"], "fecha_futura")
