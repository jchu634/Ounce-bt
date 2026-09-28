### WebSocket protocol

Connect to `ws://<host>:<port>/ws`. The server sends a `status` frame on connect and on every mode/macro transition. Text frames are JSON.

**Client → server**

```jsonc
// Full controller-state snapshot (lowest-latency manual path)
{"type": "state", "buttons": ["A","B"], "left": [0.0, 1.0], "right": [0.0, 0.0]}

// Single action (one-shot taps; for chorded input use "state")
{"type": "event", "action": {"do": "press", "button": "A"}}
{"type": "event", "action": {"do": "release", "button": "A"}}
{"type": "event", "action": {"do": "stick", "side": "left", "x": 0.0, "y": 1.0}}

// Macro control
{"type": "macro", "op": "start", "macro": {"name": "...", "repeat": 1, "actions": [...]}}
{"type": "macro", "op": "start", "name": "press-a-three-times"}   // load from macros/<name>.json
{"type": "macro", "op": "cancel"}      // immediate stop, drains queue, pushes NEUTRAL
{"type": "macro", "op": "pause"}
{"type": "macro", "op": "resume"}
```

Valid button names: `A B X Y L R ZL ZR UP DOWN LEFT RIGHT PLUS MINUS HOME CAPTURE STICK_L STICK_R`.

`event` semantics: each frame replaces the current controller state (latest-wins consumer). For chorded/persistent input, prefer `state` snapshots.

**Server → client**

```jsonc
{"type": "status", "mode": "manual"|"macro", "macro": {"name": "...", "state": "running"|"paused"}|null}
{"type": "error", "message": "...", "detail": "..."?}
```

### Macros

JSON files under `macros/`. Schema:

```jsonc
{
  "name": "example",
  "repeat": 0, // 0 = loop forever, N = play N times
  "actions": [
    { "do": "press", "button": "A" },
    { "do": "wait", "ms": 50 },
    { "do": "release", "button": "A" },
    { "do": "wait", "ms": 50 },
    { "do": "stick", "side": "left", "x": 0.0, "y": 1.0 },
    { "do": "wait", "ms": 200 },
    { "do": "stick", "side": "left", "x": 0.0, "y": 0.0 },
    {
      "do": "loop",
      "count": 3,
      "actions": [
        { "do": "press", "button": "B" },
        { "do": "wait", "ms": 30 },
        { "do": "release", "button": "B" },
        { "do": "wait", "ms": 30 },
      ],
    },
  ],
}
```
