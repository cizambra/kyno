# The MCP contract

Everything an agent or client can ask Kyno, over MCP or Python.

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
bump. It serves the compact form: a resource takes no parameters, and the
whole document is one tool call away.
