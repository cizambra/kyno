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
  means. When there is no description, the title is just a string.
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
note: the constitution as written
by: camilo
```

```bash
kyno set --file constitution.yaml
kyno set --file constitution.yaml --constitution eu --note "the EU edit"
```

The declaration can be written using markdown. How the published page
renders and escapes it is covered in
[Publishing your constitution](publishing.md).

### Editing with flags

There are two ways to pass an edit to `kyno set`: a file, or flags. Use
flags when the edit is small, or when a script needs to add information
about the run:

```bash
kyno set --mission "Ship a lending product people trust" --note "sharpen the mission"
kyno set --file constitution.yaml --by "release-bot" --note "apply the reviewed edit"
```

How the two combine:

- **`--note`, `--by`, `--constitution`**: These describe the edit, not
  the content. When the file has the same keys, the flag wins. This is
  safe because none of them can change the mission, the principles, or
  the declaration.
- **`--mission`, `--declaration`, `--principle`**: These are content.
  They can't be combined with `--file`, because two sources for the same
  field would be ambiguous.
- **Omitted fields**: They keep their previous value. To clear one,
  write it empty (e.g. `declaration: ""`).
- **Versions**: Every edit appends a new version. Previous versions are
  never modified.

Two things to watch:

- **The file is a full write, not a diff.** If you apply a stale file,
  its content becomes the newest version, and your agents serve it on
  their next pull. You can fix it with one more `kyno set`, but nothing
  warns you when it happens.
- **`--constitution` redirects the whole edit.** A file written for `eu`
  lands in `us` if the flag says so. If the file already names its
  constitution, don't pass the flag.

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
