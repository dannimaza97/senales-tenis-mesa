# PulsoPro 2 — Auditoría inicial

Fecha: 2026-11-05

## Objetivo
Recuperar el análisis estadístico usando `historico_partidos.json` sin requerir una suscripción activa a BetsAPI. Mantener intacta la rama `main`.

## Hallazgos comprobados
- `senales_reales.py` requiere `BETSAPI_TOKEN` al importar el módulo (`os.environ["BETSAPI_TOKEN"]`). No se debe iniciar el flujo de datos en directo sin credenciales válidas.
- `backtest_ganador_partido.py` carga el histórico local y trata la actualización desde BetsAPI como opcional (`os.environ.get`).
- El comentario del backtest describe aproximadamente 337.000 partidos y un histórico congelado a 2026-08-19; esa cantidad todavía no está verificada mediante recuento independiente.
- Los informes `backtest_ganador_partido_report.md` y `.json` no estaban disponibles en la raíz de `main` al revisarlos.

## Próximas tareas
1. Verificar esquema, fechas, duplicados, ligas y número de registros válidos del histórico.
2. Ejecutar backtest offline con separación cronológica y métricas Brier/log-loss/calibración.
3. Crear un modo demostración/histórico claramente etiquetado: no presentar encuentros históricos como partidos de hoy.
4. Separar la ingestión de datos en vivo del motor estadístico y manejar la ausencia de credenciales sin errores.
5. Validar legalidad, estabilidad, cobertura y costes de una nueva fuente de encuentros antes de integrarla.

## Política de señales
No publicar probabilidades o selecciones como validadas hasta comprobar su calibración fuera de muestra. Confirmar calendario, mercado y cuotas actuales de manera independiente. No inferir partidos de hoy a partir del histórico.
