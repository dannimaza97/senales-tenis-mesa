# PulsoPro 2.0 — desarrollo aislado

Esta rama **no sustituye el motor de producción**. No modifica las tablas existentes
`signals`, `resultados` ni `daily_stats`.

## Incluido
- `core.py`: validación de eventos futuros y probabilidades; métricas Brier,
  log loss y bandas de calibración.
- `historial.py`: escritura idempotente de partidos finalizados en una **tabla
  nueva** de Supabase, en lotes de 200.
- `schema.sql`: definición de tabla con RLS habilitada, sin políticas públicas.
- `tests/test_pulsopro2.py`: pruebas unitarias sin acceso a API ni secretos.
- Workflow independiente de pruebas en GitHub Actions.

## Antes de activar la persistencia
1. Revisar y ejecutar `schema.sql` en el proyecto Supabase correcto.
2. Conectar el motor de ingestión de resultados reales y mapear el marcador
   final confirmado al formato validado.
3. Verificar acceso a Supabase desde GitHub Actions sin exponer service_role.
4. Medir calibración **fuera de muestra y por orden temporal**. Las
   probabilidades deben guardarse antes del inicio del encuentro.

**Pendiente:** ingestión automática y backtest temporal, integración con
frontend y despliegue. No se ha cambiado `main`.
