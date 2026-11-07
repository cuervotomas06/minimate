-- =============================================================================
-- MiniMate: tablas en Supabase (Postgres)
-- Pegar entero en el SQL Editor de Supabase y apretar "Run".
-- Se puede volver a correr sin romper nada (usa "if not exists" / "or replace").
-- =============================================================================
--
-- Seguridad, en dos capas:
-- 1. GRANT: qué roles pueden tocar cada tabla. Como el proyecto tiene
--    desactivado "Automatically expose new tables", las tablas nuevas no son
--    accesibles por la API hasta que les damos permiso. Solo se lo damos a
--    service_role (el rol de la clave secreta, que usa la app desde el
--    servidor). anon y authenticated (los roles de la clave pública) no
--    tienen ningún permiso.
-- 2. RLS (Row Level Security): filtra fila por fila. Queda activado en todas
--    las tablas. service_role saltea el RLS (tiene el atributo BYPASSRLS),
--    así que las políticas de abajo son para dejarlo explícito y documentado;
--    para anon y authenticated NO hay políticas, o sea: no ven ni escriben nada.

-- -----------------------------------------------------------------------------
-- 1. Jugadores: una fila por persona que juega en la app.
-- -----------------------------------------------------------------------------
create table if not exists public.jugadores (
    id      uuid primary key default gen_random_uuid(),
    nombre  text not null,                    -- como lo escribiste: "Tomás"
    clave   text not null unique,             -- normalizado: "tomás" (sin repetir)
    creado  timestamptz not null default now(),
    constraint nombre_no_vacio check (length(trim(nombre)) between 1 and 40)
);

-- -----------------------------------------------------------------------------
-- 2. Partidas: una fila por partida (las mismas columnas que la tabla
--    "partidas" de src/datos.py, más el PGN completo y de quién es).
-- -----------------------------------------------------------------------------
create table if not exists public.partidas (
    id                    uuid primary key default gen_random_uuid(),
    jugador_id            uuid not null references public.jugadores (id) on delete cascade,
    origen                text not null check (origen in ('minimate', 'chesscom')),
    -- Identifica la partida para no guardarla dos veces: el link de Chess.com,
    -- o un resumen (hash) de fecha + jugadas para las de MiniMate.
    clave                 text not null,
    fecha                 timestamptz,
    color                 text not null check (color in ('blancas', 'negras')),
    nivel                 text,
    reloj                 text,
    resultado             text not null check (resultado in ('victoria', 'derrota', 'tablas', 'sin terminar')),
    terminacion           text,
    cantidad_jugadas      integer,
    eco                   text,
    apertura              text,
    jugada_enroque        integer,            -- null = nunca enroqué
    menores_desarrolladas integer,
    dama_temprana         boolean,
    mi_elo                integer,
    elo_rival             integer,
    link                  text,
    pgn                   text not null,      -- la partida entera, por si hay que recalcular
    guardada              timestamptz not null default now(),
    unique (jugador_id, clave)                -- la misma partida no entra dos veces
);

create index if not exists partidas_jugador_fecha on public.partidas (jugador_id, fecha desc);

-- -----------------------------------------------------------------------------
-- 3. Jugadas: una fila por jugada (las columnas de la tabla "jugadas" de
--    src/datos.py). "origen" y "fecha" no se repiten acá: se toman de la
--    partida (partida_id). Si se borra la partida, se borran sus jugadas.
-- -----------------------------------------------------------------------------
create table if not exists public.jugadas (
    partida_id      uuid not null references public.partidas (id) on delete cascade,
    indice          integer not null,         -- 0 = la primera media jugada
    numero          integer not null,         -- número de jugada de ajedrez
    color           text not null check (color in ('blancas', 'negras')),
    es_mia          boolean not null,
    san             text not null,
    uci             text not null,
    fen_antes       text not null,
    reloj_restante  real,
    eval_antes      real,                     -- centipeones, desde mi punto de vista
    eval_despues    real,
    mate_despues    integer,
    perdida         real,
    clasificacion   text check (clasificacion in ('imprecisión', 'error', 'error grave')),
    fase            text check (fase in ('apertura', 'medio juego', 'final')),
    pieza_colgada   boolean,                  -- null en las jugadas del rival
    captura_perdida boolean,
    primary key (partida_id, indice)
);

-- -----------------------------------------------------------------------------
-- 4. Caché de evaluaciones: posición (EPD) -> evaluación de MiniMate.
--    Es compartida: una posición vale lo mismo para todos los jugadores.
-- -----------------------------------------------------------------------------
create table if not exists public.evaluaciones (
    posicion    text primary key,             -- FEN sin los contadores de jugadas
    valor       integer not null,             -- centipeones desde blancas
    profundidad smallint not null default 2,
    creada      timestamptz not null default now()
);

-- -----------------------------------------------------------------------------
-- 5. Guardar una partida con sus jugadas, todo junto.
--    Es una "transacción": o se guardan la partida Y sus jugadas, o nada
--    (si algo falla a la mitad no queda una partida sin jugadas).
--    Si la partida ya estaba (mismo jugador y clave), no hace nada y devuelve null.
-- -----------------------------------------------------------------------------
create or replace function public.guardar_partida(p_jugador uuid, p_partida jsonb, p_jugadas jsonb)
returns uuid
language plpgsql
security invoker          -- corre con los permisos de quien la llama (service_role)
set search_path = ''      -- buena práctica: nombres siempre con "public."
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
        pieza_colgada, captura_perdida)
    select nueva, j.indice, j.numero, j.color, j.es_mia, j.san, j.uci, j.fen_antes,
           j.reloj_restante, j.eval_antes, j.eval_despues, j.mate_despues, j.perdida,
           j.clasificacion, j.fase, j.pieza_colgada, j.captura_perdida
    from jsonb_populate_recordset(null::public.jugadas, p_jugadas) as j;

    return nueva;
end;
$$;

-- -----------------------------------------------------------------------------
-- 6. Permisos (GRANT): solo service_role.
-- -----------------------------------------------------------------------------
revoke all on public.jugadores, public.partidas, public.jugadas, public.evaluaciones
    from anon, authenticated;
grant select, insert, update, delete
    on public.jugadores, public.partidas, public.jugadas, public.evaluaciones
    to service_role;

-- Las funciones nuevas, por defecto, las puede ejecutar cualquiera (PUBLIC).
revoke execute on function public.guardar_partida(uuid, jsonb, jsonb) from public, anon, authenticated;
grant execute on function public.guardar_partida(uuid, jsonb, jsonb) to service_role;

-- -----------------------------------------------------------------------------
-- 7. RLS: activado en todas (el proyecto ya lo activa solo; repetirlo no molesta).
-- -----------------------------------------------------------------------------
alter table public.jugadores    enable row level security;
alter table public.partidas     enable row level security;
alter table public.jugadas      enable row level security;
alter table public.evaluaciones enable row level security;

-- Políticas: acceso total para service_role (la app). Ninguna para anon ni
-- authenticated: con RLS activado y sin políticas, no pueden ver ni tocar nada.
drop policy if exists "app (service_role) usa jugadores" on public.jugadores;
create policy "app (service_role) usa jugadores" on public.jugadores
    for all to service_role using (true) with check (true);

drop policy if exists "app (service_role) usa partidas" on public.partidas;
create policy "app (service_role) usa partidas" on public.partidas
    for all to service_role using (true) with check (true);

drop policy if exists "app (service_role) usa jugadas" on public.jugadas;
create policy "app (service_role) usa jugadas" on public.jugadas
    for all to service_role using (true) with check (true);

drop policy if exists "app (service_role) usa evaluaciones" on public.evaluaciones;
create policy "app (service_role) usa evaluaciones" on public.evaluaciones
    for all to service_role using (true) with check (true);
