# The MCP contract

This is everything an agent or client can ask Kyno, over MCP or Python.

## The tools

- `get_constitution`: the direction in force now (mission, principles, version).
- `get_changes_since(known_version)`: the pull an agent makes before a step.
  It returns the current direction plus the change notes since the version
  the agent last saw.
  Missing a notification causes no harm, because the next pull carries
  everything needed.
- `get_mission`, `get_declaration`, `get_principles`, `get_principle(title)`:
  one piece of the document each, for when a compact read left it out.
- `set_direction(mission?, declaration?, principles?, change_note)`: append
  the next version. Omitted fields carry forward; `""` clears one. On HTTP
  this requires the bearer token.

Every read returns as little as it can by default: the titles, not the long
text. An agent pulls before every step, and would otherwise pay for the
whole document each time. Ask for more when something actually needs it:
`detail="full"` on the two pulls, `detail="full"` on `get_principles`, or one
of the targeted reads. Every answer carries the version it came from, so a
client mixing them can tell when they have drifted apart.

Clients may also subscribe to the `kyno://constitution/current` resource and
receive a standard MCP `resources/updated` notification on every version
bump. The notification is a hint, never a payload: on a wake, call
`get_changes_since` with the last version you processed and you get
everything you missed, downtime included. That makes any consumer work,
agent or not: a backend that audits every version, a job that rebuilds a
cache, or a watcher that posts the change note somewhere. The shipped
adapters don't subscribe, because the binder pulls at every step boundary
anyway.

## 💬 Questions?

[Ask one](https://github.com/cizambra/kyno/issues/new?template=question.yml)
and I'll answer there, so the next person finds it too.
