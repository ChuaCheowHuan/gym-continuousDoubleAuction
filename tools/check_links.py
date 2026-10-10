"""Check relative links and heading anchors in README.md and doc/*.md.

Usage: python tools/check_links.py [repo_root]   (default: the repository root)
Prints one `file:line problem target` per broken link; exits 1 if any.
"""
import os
import re
import sys

ROOT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LINK = re.compile(r"\]\(([^)\s]+)\)")


def slug(heading):
    s = re.sub(r"[^\w\- ]", "", heading.strip().lower())
    return s.replace(" ", "-")


def anchors(path):
    out, seen, fence = set(), {}, False
    for line in open(path, encoding="utf-8"):
        if line.lstrip().startswith("```"):
            fence = not fence
            continue
        m = None if fence else re.match(r"^#{1,6}\s+(.*)", line)
        if m:
            base = slug(m.group(1))
            n = seen.get(base, 0)
            seen[base] = n + 1
            out.add(base if n == 0 else f"{base}-{n}")
    return out


def main():
    docs = os.path.join(ROOT, "doc")
    files = [os.path.join(ROOT, "README.md")] + [
        os.path.join(docs, f) for f in sorted(os.listdir(docs)) if f.endswith(".md")]
    broken = []
    for f in files:
        fence = False
        for i, line in enumerate(open(f, encoding="utf-8"), 1):
            if line.lstrip().startswith("```"):
                fence = not fence
                continue
            if fence:
                continue
            for target in LINK.findall(line):
                if re.match(r"^[a-z]+:", target):
                    continue
                path, _, frag = target.partition("#")
                dest = f if not path else os.path.normpath(os.path.join(os.path.dirname(f), path))
                rel = os.path.relpath(f, ROOT)
                if not os.path.exists(dest):
                    broken.append(f"{rel}:{i} missing {target}")
                elif frag and dest.endswith(".md") and frag not in anchors(dest):
                    broken.append(f"{rel}:{i} anchor {target}")
    print("\n".join(broken))
    print(f"TOTAL {len(broken)} broken link(s)", file=sys.stderr)
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
