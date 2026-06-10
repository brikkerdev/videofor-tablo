CREATE TABLE IF NOT EXISTS events (
    id          BIGSERIAL PRIMARY KEY,
    event_type  TEXT        NOT NULL,
    event_time  TIMESTAMPTZ NOT NULL,
    source      TEXT        NOT NULL,
    object_type TEXT,
    checkpoint  TEXT,
    value       INTEGER     NOT NULL,
    payload     JSONB       NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_events_event_time ON events (event_time);
CREATE INDEX IF NOT EXISTS idx_events_type_time  ON events (event_type, event_time);

CREATE TABLE IF NOT EXISTS indicators (
    key          TEXT PRIMARY KEY,
    display_name TEXT    NOT NULL,
    kind         TEXT    NOT NULL CHECK (kind IN ('daily', 'gauge')),
    sort_order   INTEGER NOT NULL DEFAULT 0,
    enabled      BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS event_rules (
    event_type    TEXT NOT NULL,
    checkpoint    TEXT,
    indicator_key TEXT NOT NULL REFERENCES indicators(key),
    op            TEXT NOT NULL CHECK (op IN ('inc', 'dec', 'set')),
    enabled       BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (event_type, indicator_key)
);

CREATE TABLE IF NOT EXISTS counter_values (
    day           DATE NOT NULL,
    indicator_key TEXT NOT NULL REFERENCES indicators(key),
    value         INTEGER NOT NULL DEFAULT 0,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (day, indicator_key)
);

CREATE TABLE IF NOT EXISTS push_state (
    id        SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    pushed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS config (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO indicators (key, display_name, kind, sort_order) VALUES
    ('violations_day',       'Нарушения за день',     'daily', 10),
    ('students_on_track',    'Ученики на треке',      'gauge', 20),
    ('instructors_on_track', 'Инструкторы на треке',  'gauge', 30)
ON CONFLICT (key) DO NOTHING;

INSERT INTO event_rules (event_type, checkpoint, indicator_key, op) VALUES
    ('violation',      NULL, 'violations_day',       'inc'),
    ('student_in',     NULL, 'students_on_track',    'inc'),
    ('student_out',    NULL, 'students_on_track',    'dec'),
    ('instructor_in',  NULL, 'instructors_on_track', 'inc'),
    ('instructor_out', NULL, 'instructors_on_track', 'dec')
ON CONFLICT (event_type, indicator_key) DO NOTHING;

INSERT INTO push_state (id, pushed_at) VALUES (1, NULL)
ON CONFLICT (id) DO NOTHING;
