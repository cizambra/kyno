# Best practices

How to run Kyno once real agents depend on the store. Everything on this
page uses what ships today, and the sequence scales down: solo you are
every role, in a team the roles split. Take the rungs in order and stop
where your team is.

## Keep the constitution in version control

The store serves direction; version control explains it. Keep the file
in a repo, change it by pull request, and let the PR be the approval: what merged is
what a reviewer read, and the version's note names the commit. Kyno keeps
no approval records of its own because the audit is the join of the two
ledgers — the merged PR on one side, `kyno log` on the other.

```mermaid
---
config:
  look: handDrawn
  theme: neutral
---
flowchart LR
  E["edit constitution.yaml"] --> P["pull request"]
  P -- review, merge --> M["main"]
  M --> C["pipeline: check, set"]
  C --> K["kyno server"]
  K -- pull each step --> A["agents"]
```

## One writer

Grow toward the pipeline being the only thing that applies. People edit,
review, and read; CI writes. On day one you'll apply from a laptop, and
that's fine — remote mode asks you the [consent
question](operating.md#3-go-remote) precisely because there's no
reviewer between you and production. The day CI takes over,
applying by hand becomes the exception that stands out in the log.

## The CI recipe

Two commands. First ask: is the store where this merge assumed it was?
Compare against the parent commit's file, not your own — differing from
your own file is normal right before an apply. The commands are git's;
any VCS works, all you need is the file as it was at the parent
revision.

```bash
git show HEAD^:constitution.yaml > /tmp/parent.yaml
kyno check /tmp/parent.yaml --remote   # agree = safe, differ = fail
kyno set constitution.yaml --remote --no-interactive --note "$(git log -1 --pretty=%s)"
```

If the store matches the parent, nothing landed that your file misses:
apply. If it differs, something did — a sibling job or an unmerged hotfix
— and applying would revert it, so the job fails and someone reconciles.
`no field changed` is a clean exit, so reruns and already-applied merges
need no special case. Pass `--no-interactive` explicitly: some runners
fake a terminal, and a question that hangs a job is worse than one that
fails it.

## Rehearse before you apply

Nobody can compute what agents will do differently under a reworded
principle. So don't predict — rehearse. Apply the draft to a staging name
(`hiring-next` beside `hiring`), point a test crew or an eval at it, and
watch. Promotion is applying the same reviewed file to the real name.

## Revert, don't roll back

Want v3 back? Apply v3's content again and you get, say, v10 with v3's
content. History keeps everything, including the mistake. Recovery is
never retyping: `kyno current --yaml` reads any head back out as a file.

## When the repo and the store disagree

Two copies fall out of sync in exactly two ways, and each repair is one
command:

- **Merged, forgot to apply.** The store falls behind; agents serve old
  direction while the repo looks done. Apply main's file — the CI recipe
  above makes this structural, because merging is applying.
- **Applied, forgot to merge.** The store runs ahead; live direction has
  no reviewed home, and the next merge would silently revert it. The next
  `check --remote` against main fails and says so. To keep the change:
  `kyno current --yaml > constitution.yaml`, commit, review, merge. To
  discard it: apply main's file — the delta says it reverts, and this
  time that's the point.

## Read the ledger

`kyno log` is one line per version: who wrote it, when, who authorized it
(`operator`, `automation`, or `override`), and the note. In a healthy setup almost every line is the
pipeline's. A version somebody applied by hand is not an error — it's a
line that should have a story.
