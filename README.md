# Jarvis Core v1 — Attention Phase

This phase adds a cheap contextual attention router in front of the executive.

Core remains Jarvis. Interfaces/bodies remain thin capability providers. The LLM is still a bounded cognition resource, not the scheduler or attention engine.

## The key rule

```text
incoming event
    ↓
active goal/task match?
    ├─ yes → TASK_ROUTE
    └─ no
       ↓
cheap deterministic attention rules
       ↓
DROP | PERSIST_ONLY | EXECUTIVE | IMMEDIATE
```

A normally boring event can become important because an active goal subscribes to it. Example: `DOG_BARK` is routine until a goal says `event_subscriptions=["DOG_BARK"]`.

## Anti-boil-the-ocean behavior

High-frequency events such as these are dropped before PostgreSQL unless an active goal/task subscribes to them:

```text
LIDAR_SCAN
AUDIO_LEVEL
CAMERA_FRAME
HEARTBEAT
SENSOR_TICK
```

That means raw sensor firehoses do not automatically become event history, memory, or LLM work.

## Attention dispositions

- `DROP` — do not persist, do not route, do not invoke cognition.
- `PERSIST_ONLY` — useful history/state, but no executive attention.
- `TASK_ROUTE` — matches an active goal/task subscription; bypass normal boringness.
- `EXECUTIVE` — meaningful enough for executive handling.
- `IMMEDIATE` — safety/critical event.

Each persisted event stores `_attention` metadata in its existing JSON data field, so this phase requires **no schema migration**.

## Deploy

Push this repo to the existing GitHub repository and let Railway redeploy. Keep the same Postgres and environment variables.

Check:

```text
GET /health
```

Expected phase marker:

```json
{"status":"ok","service":"jarvis-core","phase":"v1-attention"}
```

## Inspect attention

`GET /state` now includes:

```json
"attention": {
  "last": {
    "event": "USER_ACTIVE",
    "score": 0.65,
    "disposition": "EXECUTIVE",
    "reasons": ["user presence/return may warrant action"],
    "matched_goals": []
  }
}
```

Persisted events at `/events` also contain `_attention` metadata.

## Dog-bark demonstration

Create a temporary goal:

```bash
curl -X POST 'https://YOUR-SERVICE.up.railway.app/goals' \
  -H 'Content-Type: application/json' \
  -H 'X-Jarvis-Token: YOUR_TOKEN' \
  -d '{
    "kind":"count_barks",
    "description":"Count dog barks for the active observation period",
    "priority":80,
    "event_subscriptions":["DOG_BARK"]
  }'
```

The desktop test client also supports arbitrary events:

```text
event DOG_BARK
```

With the goal active, the event will be dispositioned `TASK_ROUTE` at score `0.95`, persisted, and written to a lightweight `task_observation:<goal_id>` state record.

Without an active goal subscription, the same unknown event defaults to `PERSIST_ONLY` and never invokes cognition.

## What this phase intentionally does NOT do

- no ML attention model;
- no LLM attention calls;
- no vector database;
- no generalized task planner;
- no automatic task counter implementation yet;
- no raw LiDAR/video/audio streaming into Postgres.

The purpose is to establish the routing seam before real audio/camera perception arrives.
