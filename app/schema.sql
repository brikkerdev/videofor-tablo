create table if not exists events (
    id          bigserial primary key,
    event_type  text        not null,
    event_time  timestamptz not null,
    source      text        not null,
    object_type text,
    checkpoint  text,
    value       integer     not null,
    payload     jsonb       not null,
    received_at timestamptz not null default now()
);

create table if not exists indicators (
    key          text primary key,
    display_name text    not null,
    kind         text    not null check (kind in ('daily', 'gauge')),
    sort_order   integer not null default 0,
    enabled      boolean not null default true
);

create table if not exists event_rules (
    event_type    text not null,
    checkpoint    text,
    indicator_key text not null references indicators(key),
    op            text not null check (op in ('inc', 'dec', 'set')),
    enabled       boolean not null default true,
    primary key (event_type, indicator_key)
);

create table if not exists counter_values (
    day           date not null,
    indicator_key text not null references indicators(key),
    value         integer not null default 0,
    updated_at    timestamptz not null default now(),
    primary key (day, indicator_key)
);

create table if not exists push_state (
    id        smallint primary key default 1 check (id = 1),
    pushed_at timestamptz
);

create table if not exists config (
    key        text primary key,
    value      text not null,
    updated_at timestamptz not null default now()
);

create table if not exists observed_events (
    event_type  text primary key,
    object_type text,
    checkpoint  text,
    last_value  integer,
    count       bigint      not null default 0,
    first_seen  timestamptz not null default now(),
    last_seen   timestamptz not null default now()
);

insert into indicators (key, display_name, kind, sort_order) values
    ('violations_day',       'Нарушения за день',     'daily', 10),
    ('students_on_track',    'Ученики на треке',      'gauge', 20),
    ('instructors_on_track', 'Инструкторы на треке',  'gauge', 30)
on conflict (key) do nothing;

insert into event_rules (event_type, checkpoint, indicator_key, op) values
    ('violation',      null, 'violations_day',       'inc'),
    ('student_in',     null, 'students_on_track',    'inc'),
    ('student_out',    null, 'students_on_track',    'dec'),
    ('instructor_in',  null, 'instructors_on_track', 'inc'),
    ('instructor_out', null, 'instructors_on_track', 'dec')
on conflict (event_type, indicator_key) do nothing;

insert into push_state (id, pushed_at) values (1, null)
on conflict (id) do nothing;
