# Jarvis Core v1 — Phase 2: Memory

Jarvis Core remains the single persistent Jarvis. Desktop, PiCar, phone, speakers, and future devices are interfaces/body services. Interpretation and identity remain centralized in Core; edge/body devices handle only hardware-local, latency-sensitive, and safety-critical work.

Phase 2 turns the Phase 1 persistence layer into usable continuity:

- selected meaningful events form **episodic memories**;
- explicit durable facts/preferences can be stored as **semantic memories**;
- cognition retrieves only a small relevant memory set instead of receiving the whole history;
- memory retrieval is inspectable and tracked;
- no vector database or embeddings are required yet.

## Memory boundaries

Jarvis keeps four concepts separate:

- **Events**: immutable facts about what happened.
- **State**: what Jarvis currently believes is true.
- **Memory**: what Jarvis chooses to retain beyond the immediate event stream.
- **Goals**: what Jarvis wants to accomplish.

An event is not automatically a memory. Phase 2 deliberately forms memories only for a few meaningful event classes.

## Automatic episodic memory formation

Current deterministic rules:

- `USER_ACTIVE` on an actual absent → present transition: remember the return.
- `USER_IDLE` on an actual present → absent transition: remember the departure/idle transition.
- `USER_SPOKE`: remember what the user said as an episode.
- failed `COMMAND_RESULT`: remember the failure for later diagnostic/behavioral continuity.

Each memory includes provenance metadata in `memories.data`, including its source event, tags, formation rule, retrieval count, and last retrieval time when applicable.

Speech is stored as an **episode**, not automatically promoted to semantic truth. If the user says “the moon is made of cheese,” Jarvis should remember that the user *said it*, not silently convert it into a fact. Semantic promotion deserves a stricter pipeline later.

## Retrieval

`jarvis_core/memory.py` implements a transparent Phase 2 relevance scorer using:

1. keyword/tag overlap;
2. memory salience;
3. recency decay.

This is intentionally simple. It lets us inspect behavior before deciding whether embeddings/vector search are worth adding.

When the executive decides a user return warrants cognition, it retrieves up to five relevant memories and passes only those memories to the cognition service.

The LLM still does **not** run the executive loop. Memory is context for a bounded cognition call, not a source of executable commands.

## Existing Railway deployment

This phase makes **no database schema changes** from Core v1 Phase 1. It uses the existing `memories` table and stores richer metadata in its JSON `data` column, so your current Railway PostgreSQL service can be reused directly.

Keep the same variables:

```text
DATABASE_URL=<Railway Postgres reference>
JARVIS_INTERFACE_TOKEN=...
OPENAI_API_KEY=...
JARVIS_OPENAI_MODEL=gpt-5.6-luna
```

Push these files to the existing GitHub repository and let Railway redeploy.

Check:

```text
GET /health
```

Expected phase marker:

```json
{
  "status": "ok",
  "service": "jarvis-core",
  "phase": "v1-phase2-memory"
}
```

## Inspect memories

```text
GET /memories
GET /memories?memory_type=episodic
GET /memories?memory_type=semantic
```

`/state` now also includes a compact memory section:

```json
"memory": {
  "count": 12,
  "last_formed_ids": ["mem_..."],
  "last_retrieved_ids": ["mem_..."],
  "recent": []
}
```

## Test 1 — automatic episodic memory

Run the existing desktop interface, then type:

```text
say The blue toolbox belongs in the garage
```

Refresh:

```text
https://YOUR-SERVICE.up.railway.app/memories
```

You should see an episodic memory similar to:

```text
User said: "The blue toolbox belongs in the garage"
```

The underlying `USER_SPOKE` event remains separately available at `/events`.

## Test 2 — explicit semantic memory

For Phase 2, durable facts/preferences can be seeded explicitly through an authenticated endpoint:

```bash
curl -X POST 'https://YOUR-SERVICE.up.railway.app/memories' \
  -H 'Content-Type: application/json' \
  -H 'X-Jarvis-Token: YOUR_TOKEN' \
  -d '{
    "content":"When I return after a brief absence, I prefer Jarvis not to greet me every single time.",
    "memory_type":"semantic",
    "tags":["user","preference","return","greeting"],
    "salience":0.9
  }'
```

This is deliberately explicit. Automatic semantic extraction/promotion comes later.

## Test 3 — retrieval

```bash
curl -X POST 'https://YOUR-SERVICE.up.railway.app/memories/search' \
  -H 'Content-Type: application/json' \
  -H 'X-Jarvis-Token: YOUR_TOKEN' \
  -d '{
    "query":"user return greeting preference",
    "limit":5
  }'
```

The semantic preference above should rank highly. Retrieved memories receive `retrieval_count` and `last_retrieved_at` metadata.

## Test 4 — memory reaches cognition

With the preference above stored:

```text
idle
```

then later:

```text
active
```

The executive retrieves memories relevant to returns/greetings before invoking cognition. Jarvis may now choose `DO_NOTHING` because of the remembered preference rather than mechanically greeting every time.

Inspect:

```text
GET /state
```

Look at:

```text
memory.last_retrieved_ids
cognition.last_action
cognition.last_reason
```

This is the key Phase 2 demonstration: a durable memory from an earlier interaction can influence a later autonomous decision.

## Project layout

```text
jarvis_core/
├── memory.py            # memory formation + retrieval
├── cognition.py         # bounded LLM cognition; accepts retrieved memories
├── executive.py         # decides when to retrieve/think/act
├── state.py             # live state + memory introspection
├── main.py              # API/WebSocket gateway + memory endpoints
└── persistence/
    ├── db.py
    ├── repository.py    # memory CRUD/retrieval bookkeeping
    └── tables.py        # existing MemoryRow schema
```

The desktop and PiCar body services remain compatible with Phase 1.

## Deliberately postponed

- embedding/vector retrieval;
- automatic semantic fact extraction;
- memory consolidation/forgetting;
- entity-linked graph memory;
- contradiction resolution;
- memories formed from vision/audio semantics;
- procedural preference learning;
- Alembic migrations.

Those should follow observed behavior, not precede it.
