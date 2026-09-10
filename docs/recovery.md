# Recovering earlier direction

Restore reviewed content by applying it as a **new version**. If version 1
was correct and version 2 was a mistake, recovery creates version 3 with
version 1's content. Versions 1 and 2 remain in history.

This procedure uses existing export and apply commands. It does not reset
version numbers, replace history, or undo actions agents already took.

## 1. Contain the incorrect changes

If a write credential may be compromised, revoke it from the server's
workspace and provision a replacement for the authorized operator.
Keep the replacement out of the agent environment. See
[write access](operating.md#who-should-hold-write-access) and
[token revocation](operating.md#minting-and-revoking-tokens).

Pause affected workflows using your application's controls if they must
not continue with the incorrect direction. Kyno does not pause all agents
for you. Stop other writers while you review and apply the correction.

Revocation does not clear cached direction or cancel work already in
progress. Depending on the binder's policy, consumers can continue with
cached direction after a failed pull.

## 2. Preserve the history and identify a known-good version

Use an operator environment, not the agent process. The examples use an
existing remote profile named `ops` and a constitution named `support`.
Replace both with your actual target. The profile needs a write token for
the eventual apply; agents should retain read-only credentials.

```bash
umask 077
kyno current --remote --profile ops --constitution support
kyno history --remote --profile ops --constitution support
kyno export --remote --profile ops --constitution support > support-history.json
```

Check that export succeeded before continuing. Choose a new filename for
each incident so you do not overwrite earlier evidence. The export
contains full content and version metadata for **one constitution**, not
a backup of the whole server. Its rows do not contain the constitution
name: keep the target name with the file and confirm it when extracting.
Retain relevant request logs and any application direction receipts too.

Select a version you have reviewed, rather than assuming the oldest or
most recent one is correct. `kyno current --yaml` reads the current head;
it cannot retrieve an arbitrary historical version.

## 3. Extract complete content for review

Save this example as `extract_direction.py` in your operator environment.
It reads the export and writes an authored JSON file accepted by
`kyno apply`. It neither connects to Kyno nor changes live direction.

```python
import json
import sys

history_path, version_text, constitution, output_path = sys.argv[1:]
version = int(version_text)
with open(history_path, encoding="utf-8") as history_file:
    rows = json.load(history_file)
matches = [row for row in rows if row["version"] == version]
if len(matches) != 1:
    raise SystemExit(f"Expected exactly one version {version}; found {len(matches)}")
selected = matches[0]
content = {
    "constitution": constitution,
    "mission": selected["mission"],
    "declaration": selected["declaration"],
    "principles": selected["principles"],
}
with open(output_path, "x", encoding="utf-8") as output_file:
    json.dump(content, output_file, indent=2, ensure_ascii=False)
    output_file.write("\n")
```

To extract version 1:

```bash
python extract_direction.py support-history.json 1 support recovery.json
```

The output file must not already exist. Inspect it before applying.
The recipe copies only constitution content, not the old version number,
timestamps, author, approval method, or token identity. The corrective
write gets its own metadata.

Empty fields are intentional. `"declaration": ""` and `"principles": []`
clear those fields. Omitting them or using `null` would instead keep the
current values, which could leave unwanted content in place. The recipe
also preserves principle descriptions and an explicitly empty mission.

## 4. Review and apply as a new version

```bash
kyno apply recovery.json --remote --profile ops --dry-run
kyno apply recovery.json --remote --profile ops --note "Restore reviewed content from v1"
```

The constitution name comes from `recovery.json`. Check the target,
mission, declaration, principles, and delta, including fields being
cleared. The real apply asks for consent and can ask you to confirm that
returning to an older version's content is deliberate. Do not bypass
these questions as a substitute for reviewing the correction.

A dry run does not reserve a version or lock the head. Review the delta
again during the actual apply. If another writer changes the head during
that apply, the version check can refuse the write; inspect the new state
instead of retrying blindly.

Do **not** use `kyno import` to repair active history. Import restores a
version history into an empty target; it does not append a corrective
version to an active constitution. Do not delete historical versions.
If the current content already matches the recovery file, apply is a
no-op rather than another version.

## 5. Verify direction and resume consumers

```bash
kyno current --remote --profile ops --constitution support
kyno history --remote --profile ops --constitution support
```

Verify the full content and the new version number. Confirm the incorrect
version is still present in history. Then allow consumers to reach their
next direction boundary and inspect their bindings: the expected new
version with delivery status `current` records a successful read at that
boundary. `cached` or `empty` does not confirm a successful read of the
correction. Existing in-flight steps are not rewritten by recovery.

For per-call or per-step records, see [CrewAI recording](crewai.md#optional-recording)
and [LangGraph recording](langgraph.md#optional-recording). Kyno does not
create a central receipt database. A receipt identifies direction supplied
to a call, not proof that the model obeyed it or that the call completed.

## 6. Assess work performed under the incorrect direction

Match application receipts by **constitution and version**, then use the
application's run/step identifiers to inspect associated work. In the
example, receipts for `support` version 2 identify calls supplied with the
incorrect version. Version 3 is distinct even though its content matches
version 1.

Without these receipts, server request logs can help bound when access
occurred, but cannot establish which direction every model call received.
Cached direction can be used without a successful server request.
Decide separately whether affected outputs or external actions need
review or repair. Restoring direction does not repair them automatically.
