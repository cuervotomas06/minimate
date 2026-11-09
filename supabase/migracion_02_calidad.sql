-- =============================================================================
-- MiniMate · Migración 02: calidad de cada jugada (★ ✓ ?! ? ??)
-- Correr UNA vez en el SQL Editor de Supabase, después de la migración 01.
-- Solo agrega una columna y actualiza la función que guarda partidas.
-- Se puede volver a correr.
-- =============================================================================

-- 1. Columna nueva en jugadas: la calidad que mostró la app en vivo.
--    (Vacía en las jugadas del rival y en las partidas importadas.)
alter table public.jugadas add column if not exists calidad text;
alter table public.jugadas drop constraint if exists jugadas_calidad_check;
alter table public.jugadas add constraint jugadas_calidad_check
    check (calidad in ('mejor', 'buena', 'imprecisión', 'error', 'error grave'));

-- 2. guardar_partida: la misma de esquema.sql, ahora también con la calidad.
create or replace function public.guardar_partida(p_jugador uuid, p_partida jsonb, p_jugadas jsonb)
returns uuid
language plpgsql
security invoker
set search_path = ''
as $$
declare
    nueva uuid;
begin
    insert into public.partidas (
        jugador_id, origen, clave, fecha, color, nivel, reloj, resultado, terminacion,
        cantidad_jugadas, eco, apertura, jugada_enroque, menores_desarrolladas,
        dama_temprana, mi_elo, elo_rival, link, pgn)
    select p_jugador, r.origen, r.clave, r.fecha, r.color, r.nivel, r.reloj, r.resultado,
           r.terminacion, r.cantidad_jugadas, r.eco, r.apertura, r.jugada_enroque,
           r.menores_desarrolladas, r.dama_temprana, r.mi_elo, r.elo_rival, r.link, r.pgn
    from jsonb_populate_record(null::public.partidas, p_partida) as r
    on conflict (jugador_id, clave) do nothing
    returning id into nueva;

    if nueva is null then
        return null;  -- ya estaba guardada
    end if;

    insert into public.jugadas (
        partida_id, indice, numero, color, es_mia, san, uci, fen_antes, reloj_restante,
        eval_antes, eval_despues, mate_despues, perdida, clasificacion, fase,
        pieza_colgada, captura_perdida, calidad)
    select nueva, j.indice, j.numero, j.color, j.es_mia, j.san, j.uci, j.fen_antes,
           j.reloj_restante, j.eval_antes, j.eval_despues, j.mate_despues, j.perdida,
           j.clasificacion, j.fase, j.pieza_colgada, j.captura_perdida, j.calidad
    from jsonb_populate_recordset(null::public.jugadas, p_jugadas) as j;

    return nueva;
end;
$$;

-- 3. Permisos de la función (igual que antes: solo service_role).
revoke execute on function public.guardar_partida(uuid, jsonb, jsonb) from public, anon, authenticated;
grant execute on function public.guardar_partida(uuid, jsonb, jsonb) to service_role;
