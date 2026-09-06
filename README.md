# Jarvis Core v1 — Phase 1

Core is Jarvis. Cars, desktops, phones, speakers, and future devices are interfaces/body services. Interpretation defaults to Core; only hardware-local, latency-sensitive, or safety-critical work belongs at the edge.

This phase moves the successful distributed POC onto a persistent Core architecture.

## What changed

Jarvis now separates four kinds of truth:

- **Events** — immutable facts about what happened.
- **State** — what Jarvis currently believes is true.
- **Goals** — outcomes Jarvis wants to achieve.
- **Actions** — capability requests Jarvis attempted and their results.

A `memories` table is also present as the seam for the next phase, but automatic memory formation/retrieval is intentionally not implemented yet.

Live WebSocket connections remain in RAM. Durable interface identity/capabilities, events, world state, goals, actions, and memories live in PostgreSQL.

## Railway deployment

1. Push this version to the existing GitHub repository and allow Railway to redeploy.
2. In the same Railway project, click **+ New → Database → PostgreSQL**.
3. On the Jarvis Core service, create a variable reference named `DATABASE_URL` pointing to the PostgreSQL service's `DATABASE_URL`.
4. Keep the existing variables:

```text
JARVIS_INTERFACE_TOKEN=...
OPENAI_API_KEY=...
JARVIS_OPENAI_MODEL=gpt-5.6-luna
JARVIS_HEARTBEAT_SECONDS=2
JARVIS_SOCIAL_TRIGGER_SECONDS=20
```

On startup Core creates the Phase-1 tables automatically. This is deliberate for rapid iteration; migrate to Alembic before schema evolution becomes substantial.

Railway exposes `DATABASE_URL` on its PostgreSQL service; Core normalizes Railway's `postgresql://` URL to SQLAlchemy's explicit psycopg 3 dialect.

## Smoke test

After deployment:

```text
GET /health
GET /state
GET /events
GET /actions
GET /goals
```

Connect the existing desktop client and PiCar body exactly as before. Their protocol has not changed.

Generate a few events (`idle`, `active`, PiCar commands), then inspect `/events` and `/actions`.

### Persistence test

1. With the desktop connected, send `active` or otherwise generate events.
2. Confirm they appear at `/events`.
3. Redeploy/restart the Railway Core service.
4. Reopen `/state` and `/events`.

The WebSocket interfaces will reconnect, but historical events and persisted world state should remain.

## Data model

Tables created in Phase 1:

```text
interfaces
  durable identity + advertised capabilities + last seen

events
  immutable event history

entity_states
  current world/working state by entity

goals
  desired outcomes and status

actions
  commands sent to capabilities + results

memories
  persistent memory seam for Phase 2
```

The current `person:user` entity is intentionally generic. Identity/entity resolution comes later with perception and semantic memory.

## Architecture

```text
Interfaces / Bodies
        │
        ▼
   Event Intake ─────────────► events (Postgres)
        │
        ▼
   World State ──────────────► entity_states (Postgres)
        │
        ▼
    Executive
      │    │
 routine  cognition
      │    │
      └────┤
           ▼
        Actions ─────────────► actions (Postgres)
           │
           ▼
   Capability routing
           │
           ▼
   Interfaces / Bodies
```

## Intentional limitations

- `create_all()` bootstraps schema instead of Alembic migrations.
- Repository calls are synchronous; this is acceptable at present load and can be made async later without changing the domain model.
- Drives are still POC-quality.
- Goal execution/planning is not implemented yet.
- Memory storage exists, but memory formation/retrieval does not.
- Perception remains minimal/manual.

These are deliberate boundaries for Phase 1 rather than forgotten pieces.
