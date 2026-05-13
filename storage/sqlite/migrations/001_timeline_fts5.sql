PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS events (
  event_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL DEFAULT '2026-05-11',
  source_device_id TEXT NOT NULL,
  sensor_id TEXT NOT NULL,
  sensor_version TEXT NOT NULL DEFAULT '0.1.0',
  source_platform TEXT NOT NULL CHECK (source_platform IN ('macos', 'ios', 'watchos', 'system')),
  event_type TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  ingested_at TEXT NOT NULL,
  session_id TEXT,
  semantic_scope TEXT NOT NULL,
  dedupe_key TEXT NOT NULL,
  sensitivity TEXT NOT NULL DEFAULT 'low',
  raw_scope TEXT NOT NULL DEFAULT 'ephemeral',
  payload_json TEXT NOT NULL,
  redactions_json TEXT NOT NULL DEFAULT '[]',
  relationships_json TEXT NOT NULL DEFAULT '[]',
  tags_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_events_observed_at ON events(observed_at);
CREATE INDEX IF NOT EXISTS idx_events_platform_type ON events(source_platform, event_type);
CREATE INDEX IF NOT EXISTS idx_events_dedupe_key ON events(dedupe_key);
CREATE INDEX IF NOT EXISTS idx_events_scope ON events(semantic_scope);

CREATE VIRTUAL TABLE IF NOT EXISTS event_fts USING fts5(
  event_id UNINDEXED,
  event_type,
  semantic_scope,
  payload_text
);

CREATE TRIGGER IF NOT EXISTS trg_events_ai_event_fts
AFTER INSERT ON events
BEGIN
  INSERT INTO event_fts(event_id, event_type, semantic_scope, payload_text)
  VALUES (
    new.event_id,
    new.event_type,
    new.semantic_scope,
    coalesce(json_extract(new.payload_json, '$.text'), '') || ' ' ||
    coalesce(json_extract(new.payload_json, '$.summary'), '') || ' ' ||
    coalesce(json_extract(new.payload_json, '$.title'), '') || ' ' ||
    coalesce(json_extract(new.payload_json, '$.domain'), '') || ' ' ||
    coalesce(new.tags_json, '')
  );
END;

CREATE TRIGGER IF NOT EXISTS trg_events_au_event_fts
AFTER UPDATE ON events
BEGIN
  DELETE FROM event_fts WHERE event_id = old.event_id;
  INSERT INTO event_fts(event_id, event_type, semantic_scope, payload_text)
  VALUES (
    new.event_id,
    new.event_type,
    new.semantic_scope,
    coalesce(json_extract(new.payload_json, '$.text'), '') || ' ' ||
    coalesce(json_extract(new.payload_json, '$.summary'), '') || ' ' ||
    coalesce(json_extract(new.payload_json, '$.title'), '') || ' ' ||
    coalesce(json_extract(new.payload_json, '$.domain'), '') || ' ' ||
    coalesce(new.tags_json, '')
  );
END;

CREATE TRIGGER IF NOT EXISTS trg_events_ad_event_fts
AFTER DELETE ON events
BEGIN
  DELETE FROM event_fts WHERE event_id = old.event_id;
END;
