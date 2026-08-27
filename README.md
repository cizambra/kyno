# Kyno

[![PyPI](https://img.shields.io/pypi/v/kyno)](https://pypi.org/project/kyno/)
[![Tests](https://github.com/cizambra/kyno/actions/workflows/ci.yml/badge.svg)](https://github.com/cizambra/kyno/actions/workflows/ci.yml)
[![Python](https://img.shields.io/pypi/pyversions/kyno)](https://pypi.org/project/kyno/)
[![License](https://img.shields.io/badge/license-MIT%20%2B%20ELv2-blue)](https://github.com/cizambra/kyno/blob/main/LICENSE)
[![Site](https://img.shields.io/badge/site-cizambra.github.io%2Fkyno-blue)](https://cizambra.github.io/kyno/)

Kyno is a coherence control plane for multi-agent systems. It holds one
versioned source of truth for your system's mission and principles, its
*constitution*, and serves it over [MCP](https://modelcontextprotocol.io),
so every agent acts on the direction in force right now, even when that
direction changes mid-flight.

![An operator publishes a constitution change into Kyno, and each agent in a four-agent workflow picks the new version up at its own next step.](https://raw.githubusercontent.com/cizambra/kyno/main/docs/media/demo.gif)

## Why

Two things go wrong when every agent holds its own copy of the direction.

When goals change, an agent holding the old copy keeps producing work for
it. It gets worse: quality checks made against that stale copy push the
work back toward the obsolete goal.

And even when the direction never changes, long runs decay. Every handoff
paraphrases the mission a little, summaries compress it, and by the late
steps the system is serving an approximation of what you asked for. Like
a bad telephone game.

A static system prompt can't fix either one, because it is a copy too:
you paste it at launch, and it starts aging the moment the run begins.
Kyno removes the copy. Direction lives in one versioned store, agents pull the current
version before each step, and subscribers are notified the moment it
changes.

## How it works

- The constitution is authoritative: one record of the mission and
  principles, instead of a prompt pasted into every agent.
- Every change appends a new version with a plain-language change note.
  Nothing is edited in place.
- Agents rebind continuously: before each step, the adapter pulls the
  version in force and puts it in the context.
- A change propagates on the next pull. Nothing restarts.
- Every answer carries the version it came from, so a transcript can
  always say which direction each step served.

Kyno serves the direction and tells you when it moved. What your system
does about it belongs to your system, and that is deliberate: with the
mission and principles present at every step, your agents can judge their
own decisions against higher-level principles instead of rules alone.
This is _bottom-up agency_.

## Quick start

```bash
pip install kyno          # CLI: kyno
kyno init-db
kyno set --mission "Ship a lending product people trust" \
         --note "initial constitution"
kyno current
kyno serve --transport stdio    # or --transport http
```

`kyno current` prints the direction in force, as JSON with its version.
`kyno serve` makes it available to agents over MCP.

## Use it from an agent framework

```bash
pip install "kyno[crewai]"      # or: pip install "kyno[langgraph]"
```

```python
import kyno
from kyno.adapters.crewai import CrewAiKyno

connection = kyno.connect()  # reads KYNO_URL and KYNO_TOKEN
adapter = CrewAiKyno(connection.binder())
adapter.register()  # injects the current direction before each model call
```

That is the whole integration. Every model call runs under the version in
force, and a version published mid-run reaches the next step. Adapters
are read-only: they pull and subscribe, and never write direction on a
crew's or graph's behalf.

- [The adapters in depth](docs/adapters.md): CrewAI, LangGraph, the
  failure postures, and the realignment gate.
- [Build your own adapter](docs/integrating.md): everything you need to
  build one, for any framework or language, with a conformance checker.

## What a constitution is

A constitution is a mission plus ordered principles. The mission is the
overarching purpose, and the tie-breaker when principles conflict. Both
can hold longer prose: a declaration under the mission, a description
under any principle.

The examples in this README read like strategy, but a constitution is
not limited to it. Operational principles are just as good a use case:
your quality bar, the tone you expect, or how you prioritize.

It is written in a file:

```yaml
# constitution.yaml
mission: Ship a lending product people trust with their worst month
principles:
  - Say the hard number first
  - title: Refuse clearly
    description: |
      If we cannot lend, we say so on the first screen, and we say why.
```

```bash
kyno set --file constitution.yaml --note "the constitution as written"
```

The full file semantics, and running several constitutions side by side,
are in [Writing constitutions](docs/constitutions.md).

## Why versioning matters

Every change appends a new immutable version with a plain-language change
note. Nothing is edited in place, so the question "what was the direction
when agent X acted" always has an answer. That is what makes the record
auditable: the direction each step served is a fact you can look up.

## Self-hosting

Kyno self-hosts with no external services: SQLite out of the box,
PostgreSQL in production via `KYNO_DATABASE_URL`, served over stdio for a
local process or over HTTP with a bearer token for a fleet. A pip install
ships with its own migration scripts. The details live in [Operating Kyno](docs/operating.md).

## Documentation

The [documentation index](docs/README.md) lays these out in reading order.

- [Writing constitutions](docs/constitutions.md): the file, its fields,
  and multiple constitutions.
- [The MCP contract](docs/contract.md): every tool, the compact and full
  reads, and subscriptions.
- [The adapters in depth](docs/adapters.md): binder mechanics, failure
  postures, and the realignment gate.
- [Build your own adapter](docs/integrating.md): how to build an adapter
  in any language.
- [Publishing your constitution](docs/publishing.md): the public page,
  colors, and templates.
- [Operating Kyno](docs/operating.md): storage, auth, deploying, and testing.

## License

Two licenses, split by directory:

- The control plane (the server, store, CLI) is source-available under
  the [Elastic License 2.0](LICENSES/Elastic-2.0.txt).
- The SDK, the adapters, the conformance kit, and the integration guide
  are [MIT](LICENSES/MIT.txt).

[LICENSE](LICENSE) explains which license applies to each file.
You can build anything on the SDK, freely and commercially. What the
Elastic License restricts is offering the control plane itself as a
hosted service.

## Contributing

Issues and PRs welcome on [GitHub](https://github.com/cizambra/kyno/issues).
See [CONTRIBUTING.md](CONTRIBUTING.md) for style, test expectations, and
how licensing applies to new files.

Sibling project: [Canon](https://github.com/cizambra/canon) tests whether
your system's outputs actually cohere with the constitution Kyno serves.
