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
