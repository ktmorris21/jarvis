# Jarvis autobiographical self-memory patch

This patch closes a narrow continuity gap discovered during testing:

> Jarvis could remember what the user told him, but not what Jarvis himself had chosen or said.

## New behavior

Successful outward Core actions are now persisted as Jarvis-originated events:

```text
JARVIS_SPOKE
JARVIS_ACTED
```

For speech, only obviously self-defining utterances currently form an episodic autobiographical memory. Examples intended to match:

```text
"I choose electric blue as my favorite color."
"My favorite color is electric blue."
"I prefer concise answers."
"My name is Jarvis."
```

Routine speech does not form memory:

```text
"The time is 7:30."
"Turning left."
"Okay."
```

This is deliberately conservative. We are not implementing a full self-model, preference arbitration, or procedural learning here.

## Important distinction

A self-defining utterance creates an **episodic memory**:

```text
Jarvis said: "I choose electric blue as my favorite color."
```

It is not automatically promoted into semantic truth yet. That remains part of later semantic consolidation.

However, the episode is now available to normal memory retrieval and cognition, so follow-up questions such as "what is your favorite color?" can use Jarvis's own prior choice as context.

## Suggested test

Ask through the PiCar:

```text
Pick a favorite color.
```

Then ask:

```text
What's your favorite color?
```

Inspect:

```text
GET /events
GET /memories
GET /state
```

You should see `JARVIS_SPOKE` in the event history and an autobiographical episodic memory if Jarvis phrased the choice in a self-defining way.
