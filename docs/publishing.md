# Publishing your constitution

If you want to show people the principles you say you operate by, Kyno can
serve that page itself. The published page and the one your agents obey are
then the same record, not two copies that drift apart.

On this page:

- [Changing the colors](#changing-the-colors)
- [Using your own templates](#using-your-own-templates)
- [Placeholders](#placeholders)


```bash
kyno publish                                  # the default constitution
kyno publish --constitution eu --with-history
kyno unpublish --constitution eu
```

While `kyno serve --transport http` is running, a published constitution is
readable by anyone at:

- `GET /constitutions/{name}`: a self-contained HTML page (no scripts, no
  external assets, light and dark). The declaration is the body of it,
  rendered from markdown, and a described principle carries its paragraph.
- `GET /constitutions/{name}.json`: the same content, machine-readable.
- `GET /constitutions/` and `GET /constitutions.json`: an index of what you
  have published.

Three things worth knowing:

- **A published name has to be a slug**: lowercase letters, digits and
  single hyphens (`acme`, `acme-eu`). It's both the URL and the name your
  agents use, so Kyno refuses anything else rather than quietly rewriting it.
  Names you never publish are unrestricted.
- **Nothing is public until you publish it**, and publication is per name.
  One Kyno can hold your internal constitution and your public one side by
  side; publishing the second does nothing to the first.
- **Publishing shows the current direction only**: mission, declaration,
  principles, version, last-changed date. The version history stays private
  unless you add `--with-history`, because change notes are written for your
  operators and routinely explain why you changed course. A published history
  shows the 100 most recent versions; that's the page's contract. The full
  history stays available to authenticated callers over MCP and
  `kyno export`.

Anything you have not published answers `404`, exactly as a name that does
not exist does. Nothing on the public side reveals which of the two it was.

### Changing the colors

Six environment variables. Set the ones you care about and leave the rest:

| Variable | Default | What it colors |
| --- | --- | --- |
| `KYNO_PAGE_ACCENT` | `#6d6d66` | link underlines, principle numbers |
| `KYNO_PAGE_BACKGROUND` | `#fbfbf9` | the page |
| `KYNO_PAGE_TEXT` | `#1b1b19` | body text |
| `KYNO_PAGE_MUTED` | `#6d6d66` | labels, dates, the version stamp |
| `KYNO_PAGE_RULE` | `#e4e3de` | the hairlines between items |
| `KYNO_PAGE_FONT` | system sans | `font-family` for the page |

Unset, you get the built-in look, with its automatic dark mode. Set any color
and Kyno stops swapping the palette for dark mode, because inverting colors
you chose would give you a page you never approved. Past that point the
palette is yours. Setting only the font keeps the dark swap.

### Using your own templates

The pages Kyno serves are template files, and it will hand you the real ones:

```bash
kyno page export ./pages          # constitution.html, index.html, page.css
```

Edit them, then point Kyno at your copies. It prints these two lines for you:

```bash
export KYNO_CONSTITUTION_TEMPLATE=/srv/pages/constitution.html
export KYNO_INDEX_TEMPLATE=/srv/pages/index.html      # optional
```

That's the whole workflow. What you exported is what Kyno was already
rendering, the same files filled the same way, so you're editing a
working page rather than reconstructing one, and anything you leave alone
keeps working.

`kyno page export` refuses to overwrite files that are already there, and
writes nothing at all when it would have to.

The exported `page.css` is a starting point for your own styles: link it,
inline it, or throw it away. The `$stylesheet` placeholder below always
serves the styles built into Kyno, not your copy of them. A template that
keeps `$stylesheet` stays on the built-in look and follows the color
variables above; one that drops it is fully yours.

#### Placeholders

**`constitution.html`**

| Placeholder | What it is |
| --- | --- |
| `$stylesheet` | the whole `<style>` block: color variables + Kyno's page styles |
| `$name` | the constitution's name |
| `$mission` | the mission, or the name when there's no mission |
| `$declaration` | the declaration rendered from markdown, wrapped in its `<div>`; empty when there's none |
| `$principles` | the principles section, heading and list; empty when there are none |
| `$version` | the version number, e.g. `3` |
| `$updated` | the last-changed date, e.g. `2026-08-13` |
| `$history` | the version history block; empty unless you published history |

**`index.html`**

| Placeholder | What it is |
| --- | --- |
| `$stylesheet` | as above |
| `$items` | the list of published constitutions, or the "nothing published yet" line |
| `$count` | how many are published |

Each block placeholder brings its own wrapper and disappears entirely when it
has nothing to say, so a template never has to ask "what if there's no
declaration". That's deliberate. These are placeholders, not a template
language, with no loops, no conditions and no expressions, and the defaults are
held to the same limit, which is why they are the same files you just
exported.

This limit is also a safety feature. Kyno escapes your mission, principles
and change notes before they reach your file, and renders your declaration's
markdown with HTML disabled, so no template can turn text somebody typed into
a constitution into markup that runs. A placeholder you misspell is left
alone rather than breaking the page. And if your file is missing or
unreadable when a request arrives, Kyno serves its own page and logs a
warning, so a bad template never takes your public page down.
