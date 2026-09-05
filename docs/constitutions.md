# Writing constitutions

A constitution is a mission plus ordered principles. The mission is the
overarching purpose, and the tie-breaker when principles conflict.
A constitution isn't limited to strategy; operational principles are
just as good a use case.

On this page:

- [The file](#the-file)
- [Multiple constitutions](#multiple-constitutions)


## The file

The constitution is represented in a YAML file that contains three main
elements:

- A **mission**: The ultimate goal the system is intended to achieve. The
  mission is the tie-breaker when principles conflict.
- A set of **principles**: Each principle is defined by two parts. The
  principle itself (e.g. _Customer comes First_), and a description (e.g.
  "We always put the customer first and work backwards from their needs").
  The description is what helps settle an argument about what a principle
  means. A principle with no description is just its title.
- A **declaration**: Optional. This is a long-form document that adds more
  context about your mission and why the principles make sense. This is a
  good space to explain your _whys_.

Agents read the titles on every step, and the longer text only when they
ask for the full detail, so extra detail doesn't cost tokens on every
call.

Because long prose doesn't fit in command-line flags, a constitution is
better written in a file:

```yaml
# constitution.yaml
constitution: default
mission: Ship a lending product people trust with their worst month
principles:
  - Say the hard number first
  - title: Refuse clearly
    description: |
      If we cannot lend, we say so on the first screen, and we say why.
declaration: |
  ## What we are for

  Lending is a promise about somebody's worst month. We would rather lose
  the deal than make a promise we cannot keep.

  ## What that costs us

  - We say no early and in plain words.
  - We publish the number before the story that softens it.
```

```bash
kyno set constitution.yaml --note "the constitution as written"
```

The declaration can be written using markdown. How the published page
renders and escapes it is covered in
[Publishing your constitution](publishing.md).

### The file and the flags

The file is the only source of what the constitution is, and that
includes which one it is: the `constitution:` key names it, and a file
without one is refused, so a copy, a rename, or a recovery read always
lands where it says. The flags describe the edit: `--note` (required,
what changed and why) and `--by` (who made it, your system username when
omitted). Fields the file leaves out are carried forward from the
previous version; to clear one, write it empty, like `declaration: ""`.
And every edit appends a new version, so nothing you had is ever
overwritten.

## Multiple constitutions

One Kyno can hold several constitutions side by side, for example one per
product line or per jurisdiction. Each file says which one it is:

```yaml
# eu.yaml
constitution: eu
mission: Lend in the EU the way the EU expects
```

```bash
kyno set eu.yaml --note "the EU edit"
kyno current --constitution eu
```

Reads take the name as an option, over MCP and on the CLI, and default to
`"default"`, so a single-constitution setup only ever names it in the
file. Each name has its own version sequence: bumping `eu` to v2 leaves
`default` at whatever version it was. A name you have never written to
reads as the same version-0 empty state an untouched store does. The
subscribable resource is the default constitution's; agents on another
one pull it by name with `get_changes_since`.

## 💬 Questions?

[Ask one](https://github.com/cizambra/kyno/issues/new?template=question.yml)
and I'll answer there, so the next person finds it too.
