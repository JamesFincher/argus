CREATE CONSTRAINT event_id_unique IF NOT EXISTS
FOR (event:Event)
REQUIRE event.event_id IS UNIQUE;

CREATE INDEX event_observed_at IF NOT EXISTS
FOR (event:Event)
ON (event.observed_at);

CREATE INDEX event_type IF NOT EXISTS
FOR (event:Event)
ON (event.event_type);

CREATE INDEX concept_name IF NOT EXISTS
FOR (concept:Concept)
ON (concept.name);

// Seed query shape for workflow mining once events are mirrored from SQLite.
// MATCH (e1:Event)-[r:FOLLOWED_BY]->(e2:Event)
// WHERE r.delta_ms < 300000
// RETURN e1.event_type, e2.event_type, count(*) AS freq
// ORDER BY freq DESC
// LIMIT 25;
