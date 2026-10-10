"""Print every doc line whose stated number disagrees with the code.

Usage: python claims.py <repo_root> <facts.json>      (facts.json comes from facts.py)

Each hit is `category  file:line  claimed -> actual  | line`. History files are skipped.
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
print(f"{hits} candidate(s)", file=sys.stderr)
