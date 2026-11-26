# Proposal (line E): reading and tightening duck settings over duck-link

[繁體中文](e-settings-over-duck-link.md)

- Source: line E (`robot/settings/`, [ADR-0019](../../docs/adr/ADR-0019-duck-settings-page.md)), 2026-11-26
- Status: **proposal**. The schema is unchanged and neither end implements this. Whether and when to do it is the integration line's call; if adopted, change the schema and bump its version first, then both ends.

## 1. Why

Duck settings can currently be changed only from the duck's local settings web page (ADR-0019). Two situations need Nous:

1. The user asks Nous "does the duck turn towards sound right now?" or "why doesn't the duck nod?" — Nous must be able to **read** settings instead of guessing.
2. The user says "duck, stop turning your head" or "be quieter" — Nous must be able to **turn one item off or down**.

Out of scope: Nous re-enabling a disabled feature, loosening any cap, or changing body measurements. Only a person can do those, from the settings page or the local command line (ADR-0006 §3: identification is not authorisation; ADR-0019 §2.5).

## 2. Proposed actions

### 2.1 `settings_get` (read)

- `params`: `{ "keys": ["features.track_sound", …] }`, optional (omitted = all).
- `ack.data`: `{ "schema_version": 1, "revision": {"preference": 12, "measurement": 3}, "settings": { "<key>": { "value": …, "default": …, "status": "implemented" | "planned" | "hardware_missing", "effective": true | false } } }`
- `effective` is computed on the duck from what each service reports (the settings page's "applied"). For items whose `status` is not `implemented`, Nous **must not** describe them as something the duck can do (honesty rule).
- No other local information is returned (paths, change log).

### 2.2 `settings_tighten` (reversible_write)

- `params`: `{ "changes": { "<key>": <value> } }`
- The duck calls the store with source `duck_link` (the rules already exist in `duck_settings.store` and are tested, but **no code calls the store with this source today**):
  - Only the "tighter" direction is accepted: boolean feature switches only `true → false`; privacy settings only towards stricter; numbers with cap semantics (volume cap, motion amplitude, angular speed) only downwards.
  - Body measurements cannot be changed; items that are "planned" or "hardware missing" cannot be written.
  - Ranges follow the schema; out-of-range values are rejected, not clamped.
- `ack`: `accepted` on success, with the values actually written in `applied`; a change in the wrong direction is `rejected` with `reason: privacy` (privacy items) or `invalid` (others), and `detail` names the item.
- Read-back: the Nous side counts the change as `confirmed` only when `settings_get` shows the new `value` and `effective: true`; a correct value with `effective: false` (for example an item that needs a restart) is `unconfirmed`.

**What the store does not do yet**: "tighten only" is currently defined only for privacy settings (the `tighten` order). Feature switches and numbers need a per-item "tighter direction" in the schema before this action can be enabled.

### 2.3 `capabilities` and `hello`

- No new capability names. When a feature is disabled in settings, reuse the existing `capabilities.<name>`: `status: unsupported`, `reason: "disabled in duck settings"` (this version of duckd already reports `tracking_sound` this way; with gestures disabled, `hello.gestures` is empty and the `ack` is `unsupported`).
- Suggest adding `disabled` to the ack `reason` enum, separate from the "hardware absent" meaning of `unsupported`, so Nous can tell the user "this is turned off in the duck's settings" rather than "the duck can't".

### 2.4 Event

- Suggest an event `settings_changed`: `data: { "keys": […], "source": "web" | "local_cli" | "duck_link" }`, so Nous learns that a person changed settings without polling. No values (use `settings_get` for those).

## 3. Nous-side tools (when moved back into AIOS)

| Tool | effect | Notes |
|---|---|---|
| `app.duck.settings_get` | `read` | Read the duck's settings |
| `app.duck.settings_tighten` | `reversible_write` | Can only turn things off or down; "reversible" means a person can change it back on the settings page — Nous itself cannot |

There is no `app.duck.settings_set`. This has the same shape as `app.duck.privacy_tighten` in ADR-0006 §6; whether to merge the two should be decided together with the privacy policy document (`privacy_policy`).

## 4. Open questions

1. Which side is authoritative for privacy settings (ADR-0006 says stored in Nous and synced to the duck; this version of ADR-0019 stores them on the duck).
2. Whether `settings_tighten` should distinguish "for this conversation" from "until changed".
3. How to define the "tighter direction" for numbers (for example the speech energy threshold: is raising it tighter, or just different?).
