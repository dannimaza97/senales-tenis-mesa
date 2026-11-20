-- Ejecutar manualmente en el editor SQL de Supabase antes de activar el almacenamiento.
-- Solo el backend con service_role puede escribir; no exponer la clave al navegador.
create table if not exists public.pulsopro2_partidos (
  event_id text primary key,
  liga text not null,
  home text not null,
  away text not null,
  hora_ts bigint not null check (hora_ts > 0),
  sets_home integer not null check (sets_home between 0 and 3),
  sets_away integer not null check (sets_away between 0 and 3),
  creado_en timestamptz not null default now(),
  constraint marcador_final_valido check (
    (sets_home = 3 and sets_away < 3) or
    (sets_away = 3 and sets_home < 3)
  )
);
alter table public.pulsopro2_partidos enable row level security;
-- Sin politicas publicas: el acceso anonimo no puede leer ni modificar.
create index if not exists pulsopro2_partidos_hora_idx
  on public.pulsopro2_partidos (hora_ts);
