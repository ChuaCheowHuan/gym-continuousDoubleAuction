"""Print every doc line whose stated number disagrees with the code.

Usage: python claims.py <repo_root> <facts.json>      (facts.json comes from facts.py)

Each hit is `category  file:line  claimed -> actual  | line`. History files are skipped.
Beyond the number categories it checks the per-file inventory table in doc/10 (a wrong
count, a stale row, a test file with no row), the code size in doc/14, and whether every
config key and CLI flag in facts.json is mentioned in some doc at all.
A hit is a candidate, not a verdict: a historical line ("193 to 216 with the own-book block")
is left alone, and so is a number that merely sits near a noun (a "1,000-unit drawdown").
"""
import glob
import json
import os
import re
import sys

ROOT, FACTS = sys.argv[1], sys.argv[2]
SKIP = {"16_verification_log.md", "17_changelog.md", "README_v1.md", "27_agent_skills.md"}
f = json.load(open(FACTS))
WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8}
NUM = r"(\d[\d,]*|" + "|".join(WORDS) + r")"


def val(tok):
    tok = tok.lower().replace(",", "")
    return WORDS.get(tok, int(tok) if tok.isdigit() else None)


# category -> (regex with the number as group 1, set of acceptable values)
CHECKS = {
    "unit tests": (rf"{NUM}[- ]unit[- ]tests?", {f["tests"]["unit"]}),
    "integration": (rf"{NUM}[- ]integration[- ]tests?", {f["tests"]["integration"]}),
    # only suite-sized figures; per-file and per-class counts are checked below
    "suite total": (rf"{NUM}[- ]tests?\b(?! in)", {f["tests"]["total"], f["tests"]["unit"], f["tests"]["integration"]}),
    "obs width": (rf"{NUM}[- ]floats?\b", {f["obs"]["train_width"], f["obs"]["levels_width"], f["obs"]["private_dim"],
                                          f["obs"]["grid_snapshot"], f["obs"]["levels_snapshot"]}),
    "action heads": (rf"{NUM}[- ]heads?\b", {f["action"]["_heads"]}),
    "reward terms": (rf"{NUM}[- ](?:signed )?(?:reward )?terms?\b", {len(f["reward_terms"])}),
    "encoders": (rf"{NUM}[- ]encoders?\b", {len(f["encoders"])}),
}
files = [os.path.join(ROOT, "README.md")] + sorted(
    p for p in glob.glob(os.path.join(ROOT, "doc", "*.md")) if os.path.basename(p) not in SKIP)
MIN = {"suite total": 1000, "obs width": 100, "encoders": 3}   # smaller figures are per-class or sub-block counts
FILE_COUNT = re.compile(r"`(?:integration/)?(test_\w+\.py)(?:::\w+)?`[^\n]{0,30}?\b(\d+) tests?\b")
per_file = {os.path.basename(k): v for k, v in f["tests"]["per_file"].items()}
hits = 0
for path in files:
    for n, line in enumerate(open(path, encoding="utf-8"), 1):
        for m in FILE_COUNT.finditer(line):
            name, claimed = m.group(1), int(m.group(2))
            if "::" not in line[m.start():m.end()] and name in per_file and per_file[name] != claimed:
                hits += 1
                print(f"{'file count':12s} {os.path.relpath(path, ROOT)}:{n}  {name} {claimed} -> {per_file[name]}")
        for cat, (pat, ok) in CHECKS.items():
            for m in re.finditer(pat, line, re.I):
                v = val(m.group(1))
                if v is not None and v >= MIN.get(cat, 0) and v not in ok:
                    hits += 1
                    actual = "/".join(str(x) for x in sorted(ok))
                    print(f"{cat:12s} {os.path.relpath(path, ROOT)}:{n}  {m.group(1)} -> {actual}  | {line.strip()[:120]}")


# --- what the numeric categories above cannot see ---------------------------------
# The per-file inventory table, the code size, and whether a config key or a CLI flag
# is mentioned anywhere at all. Same rule: a hit is a candidate, not a verdict.
INVENTORY_ROW = re.compile(r"^\|\s*`(?:integration/)?(test_\w+\.py)`\s*\|\s*(\d+)\s*\|")
CODE_SIZE = re.compile(r"([\d,]+) lines across (\d+) Python files")
INVENTORY_DOC = "10_testing.md"
mentioned_in_inventory = set()
for path in files:
    base = os.path.basename(path)
    for n, line in enumerate(open(path, encoding="utf-8"), 1):
        m = INVENTORY_ROW.match(line)
        if m and base == INVENTORY_DOC:
            name, claimed = m.group(1), int(m.group(2))
            mentioned_in_inventory.add(name)
            if name in per_file and per_file[name] != claimed:
                hits += 1
                print(f"{'inventory':12s} {os.path.relpath(path, ROOT)}:{n}  {name} {claimed} -> {per_file[name]}")
            elif name not in per_file:
                hits += 1
                print(f"{'inventory':12s} {os.path.relpath(path, ROOT)}:{n}  {name} is listed but no longer collected")
        m = CODE_SIZE.search(line)
        if m and "code" in f:
            lines, count = int(m.group(1).replace(",", "")), int(m.group(2))
            if (lines, count) != (f["code"]["lines"], f["code"]["files"]):
                hits += 1
                print(f"{'code size':12s} {os.path.relpath(path, ROOT)}:{n}  {lines:,} lines / {count} files -> "
                      f"{f['code']['lines']:,} / {f['code']['files']}  | {line.strip()[:100]}")

for name in sorted(set(per_file) - mentioned_in_inventory):
    hits += 1
    print(f"{'inventory':12s} doc/{INVENTORY_DOC}  {name} ({per_file[name]} tests) has no row")

corpus = "\n".join(open(p, encoding="utf-8").read() for p in files)


def leaves(tree, prefix=""):
    for key, value in tree.items():
        if key.startswith("_"):          # _note, _source: prose, not settings
            continue
        if isinstance(value, dict) and value:
            yield from leaves(value, prefix + key + ".")
        else:
            yield prefix + key


for config_file, tree in f.get("config", {}).items():
    for key in leaves(tree):
        leaf = key.split(".")[-1]
        if not re.search(r"(?<![\w-])" + re.escape(leaf) + r"(?![\w])", corpus):
            hits += 1
            print(f"{'config key':12s} config/{config_file}  {key} is mentioned in no doc")
for module, flags in f.get("flags", {}).items():
    for flag in flags:
        if flag != "--help" and not re.search(re.escape(flag) + r"(?![\w-])", corpus):
            hits += 1
            print(f"{'cli flag':12s} {module}  {flag} is mentioned in no doc")
print(f"{hits} candidate(s)", file=sys.stderr)
