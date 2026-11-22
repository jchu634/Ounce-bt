### WebSocket Protocol Documentation

Connect to `ws://<host>:<port>/ws`.\
Default: `127.0.0.1:9127`\
The server sends a `status` frame on connect and on every mode/macro transition.

## Server → client

### Standard Status packet

```jsonc
{
  "type": "status",
  "mode": "manual"|"macro",
  "macro":
    {
      "name": "...",
      "state": "running"|"paused"
    }
}
```

For a multi-adapter selection, the frame also includes an `adapter_statuses`
object keyed by adapter ID. Each entry contains its own `mode` and `macro`.
The top-level status fields describe the first selected adapter.

### Standard Error packet

```jsonc
{
  "type": "error",
  "message": "...",
  "detail": "...",
}
```

## Client → server

```jsonc
// Set the input targets for this connection (defaults to primary)
{"type": "select_adapter", "adapter_id": "adapter-2"}
{"type": "select_adapters", "adapter_ids": ["primary", "adapter-2"]}

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

Valid button names: `A B X Y L R ZL ZR UP DOWN LEFT RIGHT PLUS MINUS HOME CAPTURE STICK_L STICK_R SL SR`. Macros also accept `SL_OR_L` and `SR_OR_R`, which map to `SL`/`SR` on a sideways Joy-Con and `L`/`R` otherwise.

`event` semantics: each frame replaces the current controller state (latest-wins consumer). For chorded/persistent input, prefer `state` snapshots.

Manual input reaches each selected adapter that is in manual mode. Start runs
the macro on each idle adapter. Pause, resume, and cancel apply to the selected
adapters' own playback, including any macro started before the selection changed.

### Macros

JSON files under `macros/`.

Wait actions can include an optional `unit` field of `"ms"` or `"seconds"` to
restore the visual editor's last selected unit.
E.g. `{"do": "wait", "ms": 1500, "unit": "seconds"}` displays as 1.5 seconds.
This also applies to the wait inside a press and hold block.
Defaults as ms. This is purely cosmetic.

#### Example:

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
