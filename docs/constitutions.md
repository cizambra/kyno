# Writing constitutions

A constitution is a mission plus ordered principles. The mission is the
overarching purpose, and the tie-breaker when principles conflict.
A constitution isn't limited to strategy; operational principles are
just as good a use case.

On this page:

- [The file](#the-file)
- [Multiple constitutions](#multiple-constitutions)


## The file

A one-line principle is a short name for an idea, not the full rule. The
full rule goes in a description, and the compact pull carries only the
titles, so detail costs tokens only when a read asks for it. Each of
these is optional:

- a declaration: the long-form document that the mission is the headline of;
- a description under any principle: the paragraph that settles an
  argument about what the principle means.

Both are prose, and long prose doesn't fit in command-line flags, so a
constitution is written in a file:

```yaml
# constitution.yaml
mission: Ship a lending product people trust with their worst month
declaration: |
  ## What we are for

  Lending is a promise about somebody's worst month. We would rather lose
  the deal than make a promise we cannot keep.

  ## What that costs us

  - We say no early and in plain words.
  - We publish the number before the story that softens it.
principles:
  - Say the hard number first
  - title: Refuse clearly
    description: |
      If we cannot lend, we say so on the first screen, and we say why.
note: the constitution as written
by: camilo
```

```bash
kyno set --file constitution.yaml
kyno set --file constitution.yaml --constitution eu --note "the EU edit"
```

The declaration is markdown, and the published page renders it: headings,
lists, emphasis, quotes, links. Raw HTML inside it is escaped instead of
passed through, and `javascript:` links are refused. The page is served to
anonymous visitors, so text you typed must never reach them as markup that
runs. Images aren't rendered either; that's what keeps the page one
self-contained response.

Everywhere else the declaration stays exactly the markdown you wrote. The
JSON endpoint, the MCP tools and `kyno export` all serve the source, not the
rendered document.

`--note`, `--by` and `--constitution` may override the file, because they
describe this edit rather than the constitution. The field flags
(`--mission`, `--declaration`, `--principle`) can't be combined with
`--file`, because two sources for the same field would be ambiguous. Fields
the file leaves out are carried forward from the previous version; to clear
one, write it empty, like `declaration: ""`.

The flags are still there for a quick edit:

```bash
kyno set --mission "Ship a lending product people trust" --note "sharpen the mission"
```

## Multiple constitutions

One Kyno can hold several constitutions side by side, for example one per
product line or per jurisdiction. Every operation takes an optional
`constitution` name, over MCP and on the CLI (`--constitution eu`), and
defaults to `"default"`, so a single-constitution setup never has to mention
it. Each name has its own version sequence: bumping `eu` to v2 leaves
`default` at whatever version it was. A name you have never written to reads
as the same version-0 empty state an untouched store does. The subscribable
resource is the default constitution's; agents on another one pull it by name
with `get_changes_since`.

## 💬 Questions?

[Ask one](https://github.com/cizambra/kyno/issues/new?template=question.yml)
and I'll answer there, so the next person finds it too.
