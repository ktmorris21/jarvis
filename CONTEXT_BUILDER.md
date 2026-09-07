# Jarvis v1 — Cognitive Context Builder

This revision addresses the gap exposed by conversational testing: Jarvis had durable memory, but the LLM was often receiving too little **active context** to converse naturally.

## Mental model

```text
Long-term storage                        Active cognition
-----------------                        ----------------
events                                   identity
semantic/episodic memories --candidates-> recent verbatim turns
world/entity state                       active goals
active goals                             relevant world state
                                         LLM-selected memories
                                              |
                                              v
                                         cognition
                                              |
                                  response + structured proposals
                                              |
                                    Core validates/persists
```

The model is still **Core = Jarvis**. The LLM performs semantic judgment; Core owns durable records and integrity.

## What changed

### 1. Working memory

The last 16 user/Jarvis turns are kept verbatim in `conversation:primary` using the existing `entity_states` table. A 10-minute gap starts a fresh active conversation. Durable memories and event history are unaffected.

This is what should make:

```text
User: Pick a favorite color.
Jarvis: ...
User: No, pick one yourself.
```

stay about **color**, rather than retrieving a loosely related favorite-animal memory.

### 2. Context candidate gathering

Core gathers a bounded packet:

- Jarvis identity/self instructions;
- recent verbatim conversation;
- up to 8 active goals;
- bounded current world state relevant to Jarvis/user/active goals;
- up to 12 durable memory candidates from cheap keyword/salience/recency retrieval.

Core does not dump Jarvis's entire memory database into the prompt.

### 3. LLM context selection

A bounded selector call receives the candidate memories and chooses at most 6 IDs that actually matter to the current moment. Only those selected memories become active durable context for the response.

If selection fails, conversation continues with working memory/goals/state and no durable memories.

### 4. Structured cognition side effects

The response call returns:

- `speech`;
- up to 2 semantic `memory_proposals`;
- up to 1 `goal_proposal`.

Examples of good memory proposals:

```text
Jarvis's favorite color is electric blue.
Kenneth prefers Jarvis not to greet him after brief absences.
The blue toolbox belongs in the garage.
```

Examples that should not become durable memory:

```text
Kenneth sounds tired tonight.
Jarvis just said hello.
A joke from this conversation.
```

Core does **not** semantically reinterpret proposals. It enforces only bounded count, schema, confidence threshold, exact deduplication, and persistence.

Goal proposals are accepted only at high confidence and the cognition prompt is instructed to propose them only for explicit ongoing requests such as monitor/count/wait-for tasks.

### 5. Introspection

```text
GET /context
GET /state
```

`/context` shows the latest system-level context assembly:

- working turns;
- active goal IDs;
- candidate memory IDs;
- selected memory IDs;
- selector reason;
- accepted/rejected memory/goal proposals.

This is **not hidden chain-of-thought**. It is the explicit context-routing metadata our architecture creates for debugging.

## Railway

No database migration is required. Working memory and context traces use the existing `entity_states` table; semantic proposals use the existing `memories` table; goal proposals use the existing `goals` table.

Push this revision to the existing repo and allow Railway to redeploy. Existing environment variables continue to work. New context variables have defaults and are optional.

`GET /health` should report:

```json
{"status":"ok","service":"jarvis-core","phase":"v1-cognitive-context"}
```

## Recommended tests

### Conversational reference

```text
What is your favorite color?
No, pick one yourself.
Why that one?
What color did you pick?
```

Inspect `/context`: the recent turns should be present verbatim.

### Self-choice continuity

```text
Pick a favorite animal.
Why did you choose that?
What's your favorite animal?
```

The LLM may propose the stable choice as semantic memory. Later turns should have both working continuity and, after the conversation expires, durable memory available as a candidate.

### Goal awareness

If an active goal already exists (for example a dog-bark counting goal), `/context` should show that goal supplied to cognition even during ordinary conversation. The goal is part of Jarvis's ongoing state, not a chat-only memory.

## Scope deliberately deferred

- vector database / embeddings;
- unlimited transcript retention in prompts;
- procedural learning;
- elaborate semantic graphs;
- automatic contradiction resolution;
- multi-step planning;
- streaming latency optimization.

The purpose of this revision is to make the **active slice of Jarvis's mind** coherent before making the memory system more sophisticated.
