-- =============================================================================
-- MiniMate · Migración 01: cuentas de usuario (Google, Lichess, Chess.com)
-- Correr UNA vez en el SQL Editor de Supabase, DESPUÉS de esquema.sql.
-- No toca los datos que ya hay: solo agrega cosas. Se puede volver a correr.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. Cuentas vinculadas: cada fila une un jugador de MiniMate con una cuenta
--    externa (de Google, Lichess o Chess.com).
-- -----------------------------------------------------------------------------
create table if not exists public.cuentas (
    id          uuid primary key default gen_random_uuid(),
    jugador_id  uuid not null references public.jugadores (id) on delete cascade,
    proveedor   text not null check (proveedor in ('google', 'lichess', 'chesscom')),
    -- Identificador que da el proveedor y que nunca cambia:
    --   Google: el "sub" (no el email); Lichess: el id de la cuenta;
    --   Chess.com: el player_id (aunque cambies de usuario, sigue igual).
    id_externo  text not null,
    usuario     text,                         -- nombre visible: "mantarraya1938"
    verificado  boolean not null default false,
    vinculada   timestamptz not null default now(),
    -- Cada cuenta externa puede estar vinculada a UN solo jugador.
    unique (proveedor, id_externo)
);

create index if not exists cuentas_jugador on public.cuentas (jugador_id);

-- -----------------------------------------------------------------------------
-- 2. Lichess como origen de partidas (antes solo minimate y chesscom).
--    Postgres le puso a la regla el nombre "partidas_origen_check".
-- -----------------------------------------------------------------------------
alter table public.partidas drop constraint if exists partidas_origen_check;
alter table public.partidas add constraint partidas_origen_check
    check (origen in ('minimate', 'chesscom', 'lichess'));

-- -----------------------------------------------------------------------------
-- 3. Juntar dos jugadores en uno: pasa las partidas y las cuentas de
--    p_desde a p_hacia y borra p_desde. Se usa para:
--    - pasar tus partidas viejas (jugador "mantarraya") a tu cuenta de Google;
--    - si entraste primero con Lichess y después vinculás Lichess a Google.
--    Las partidas que p_hacia ya tiene (misma clave) no se duplican.
--    Todo en una transacción. Devuelve cuántas partidas se movieron.
-- -----------------------------------------------------------------------------
create or replace function public.fusionar_jugadores(p_desde uuid, p_hacia uuid)
returns integer
language plpgsql
security invoker
set search_path = ''
as $$
declare
    movidas integer;
begin
    if p_desde = p_hacia then
        return 0;
    end if;
    -- Repetidas: las borramos de p_desde (sus jugadas se borran solas).
    delete from public.partidas as d
    where d.jugador_id = p_desde
      and exists (select 1 from public.partidas as h
                  where h.jugador_id = p_hacia and h.clave = d.clave);
    update public.partidas set jugador_id = p_hacia where jugador_id = p_desde;
    get diagnostics movidas = row_count;
    update public.cuentas set jugador_id = p_hacia where jugador_id = p_desde;
    delete from public.jugadores where id = p_desde;
    return movidas;
end;
$$;

-- -----------------------------------------------------------------------------
-- 4. Permisos: igual que el resto, solo service_role (la app, desde el servidor).
-- -----------------------------------------------------------------------------
revoke all on public.cuentas from anon, authenticated;
grant select, insert, update, delete on public.cuentas to service_role;

revoke execute on function public.fusionar_jugadores(uuid, uuid) from public, anon, authenticated;
grant execute on function public.fusionar_jugadores(uuid, uuid) to service_role;

-- -----------------------------------------------------------------------------
-- 5. RLS: activado, con acceso solo para service_role. Sin políticas para
--    anon ni authenticated: no ven ni tocan nada.
-- -----------------------------------------------------------------------------
alter table public.cuentas enable row level security;

drop policy if exists "app (service_role) usa cuentas" on public.cuentas;
create policy "app (service_role) usa cuentas" on public.cuentas
    for all to service_role using (true) with check (true);
