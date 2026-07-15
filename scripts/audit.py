#!/usr/bin/env python3
"""
audit.py — deterministic static checks for a Claude Code skill.

This is the half of skill-doctor that must not vary between runs. It reads a
skill folder, runs computable checks against the SKILL.md and its supporting
files, and prints structured findings. The judgment half (is this description
pushy enough? is this the delta or filler?) lives in the skill body + rubric and
is applied by the model; nothing subjective belongs here.

Usage:
    python3 audit.py <path-to-skill-folder> [--json]

Exit code is 0 unless the target could not be read at all (so a skill with
findings still exits 0 — findings are data, not failures).
"""

import argparse
import json
import os
import re
import sys

# Thresholds drawn from the book. Kept here, in code, so they are exact.
DESC_MAX_CHARS = 1024          # spec hard limit
DESC_SHORT_CHARS = 200         # below this, a description rarely carries a trigger surface
NAME_MAX_CHARS = 64            # spec hard limit
BODY_WARN_LINES = 500          # "keep the body under 500 lines"
BODY_WARN_TOKENS = 5000        # "under 5k tokens"
REF_TOC_LINES = 200            # a reference past this should carry a table of contents
CHARS_PER_TOKEN = 4            # rough token estimate; deterministic, not exact

NAME_RE = re.compile(r"^[a-z0-9-]+$")
# A pointer to a bundled file (references/foo.md, scripts/bar.py, ./baz.md, foo.md)
POINTER_RE = re.compile(r"(references/|scripts/|assets/|\./)?[\w-]+\.(md|py|sh|txt|json|ya?ml)")
# Words that turn a pointer from a footnote into a trigger.
CONDITION_WORDS = re.compile(r"\b(before|after|if|when|whenever|unless|while|once|for any|for each)\b", re.I)


def finding(check, severity, message, detail=None):
    """severity: error | warn | info | ok"""
    f = {"check": check, "severity": severity, "message": message}
    if detail is not None:
        f["detail"] = detail
    return f


def parse_frontmatter(text):
    """
    Minimal, dependency-free YAML frontmatter parser. Handles the two fields a
    skill actually uses (name, description), including block scalars (>- and |)
    and simple folded multi-line values. Returns (frontmatter_dict, body_str) or
    (None, text) if there is no frontmatter.
    """
    if not text.startswith("---"):
        return None, text
    lines = text.splitlines()
    # find the closing '---'
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return None, text

    fm_lines = lines[1:end]
    body = "\n".join(lines[end + 1:]).lstrip("\n")

    fm = {}
    key = None
    block_mode = False
    block_indent = None
    buf = []

    def flush():
        nonlocal key, buf
        if key is not None:
            fm[key] = " ".join(part.strip() for part in buf).strip()
        key, buf[:] = None, []

    for raw in fm_lines:
        m = re.match(r"^([A-Za-z0-9_-]+):\s?(.*)$", raw)
        if m and not (block_mode and raw.startswith(" ")):
            flush()
            block_mode = False
            key = m.group(1)
            val = m.group(2)
            if val.strip() in (">", "|", ">-", "|-", ">+", "|+"):
                block_mode = True
                block_indent = None
                buf = []
            else:
                buf = [val]
        else:
            # continuation line (block scalar or wrapped value)
            if key is not None:
                buf.append(raw)
    flush()
    return fm, body


def check_skill(path):
    findings = []
    folder = os.path.basename(os.path.normpath(path))
    skill_md = os.path.join(path, "SKILL.md")

    if not os.path.isdir(path):
        return None, [finding("target", "error", f"Not a directory: {path}")]
    if not os.path.isfile(skill_md):
        return None, [finding("SKILL.md", "error", "No SKILL.md found in the skill folder")]

    with open(skill_md, encoding="utf-8") as fh:
        raw = fh.read()

    fm, body = parse_frontmatter(raw)
    if fm is None:
        findings.append(finding("frontmatter", "error",
                                "No YAML frontmatter — a skill needs `name` and `description`"))
        fm = {}

    # --- name ---
    name = fm.get("name")
    if not name:
        findings.append(finding("name", "error", "Frontmatter is missing `name`"))
    else:
        if name != folder:
            findings.append(finding("name", "error",
                                    f"`name` ({name!r}) does not match folder ({folder!r}); "
                                    "case matters on macOS/Linux"))
        if not NAME_RE.match(name):
            findings.append(finding("name", "error",
                                    f"`name` must be lowercase letters, digits, hyphens only: {name!r}"))
        if len(name) > NAME_MAX_CHARS:
            findings.append(finding("name", "error",
                                    f"`name` is {len(name)} chars (max {NAME_MAX_CHARS})"))
        if not any(f["check"] == "name" for f in findings):
            findings.append(finding("name", "ok", f"`name` is valid and matches folder ({name})"))

    # --- description: the gate ---
    desc = fm.get("description")
    if not desc:
        findings.append(finding("description", "error",
                                "Frontmatter is missing `description` — the skill will never fire"))
    else:
        n = len(desc)
        if n > DESC_MAX_CHARS:
            findings.append(finding("description", "error",
                                    f"`description` is {n} chars (spec max {DESC_MAX_CHARS})"))
        elif n < DESC_SHORT_CHARS:
            findings.append(finding("description", "warn",
                                    f"`description` is only {n} chars — likely too short to enumerate a "
                                    "trigger surface. The gate decides whether the skill fires at all; "
                                    "use the room (up to 1024 chars).",
                                    detail=desc))
        else:
            findings.append(finding("description", "info",
                                    f"`description` is {n}/{DESC_MAX_CHARS} chars. Judgment check pending: "
                                    "does it say both WHAT and WHEN, enumerate the words you'd actually "
                                    "type, read as pushy, and close the escape hatch?",
                                    detail=desc))
        if "<" in desc or ">" in desc:
            findings.append(finding("description", "warn",
                                    "`description` contains angle brackets — these can inject structure "
                                    "into the system prompt. Remove them."))
        # cheap signal for the model: does it contain an imperative 'use ...when' cue?
        if not re.search(r"\buse (this|when|whenever)\b", desc, re.I):
            findings.append(finding("description", "info",
                                    "No explicit 'use when/whenever' cue found — the model under-fires "
                                    "skills; a pushy 'Use this whenever …' clause raises the trigger rate."))

    # --- body size ---
    body_lines = body.count("\n") + 1 if body.strip() else 0
    body_tokens = len(body) // CHARS_PER_TOKEN
    if body_lines > BODY_WARN_LINES:
        findings.append(finding("body-size", "warn",
                                f"Body is {body_lines} lines (>{BODY_WARN_LINES}). Bloat dilutes the "
                                "load-bearing lines and can make a skill net-negative. Consider splitting "
                                "into references/ or cutting content the model already knows."))
    if body_tokens > BODY_WARN_TOKENS:
        findings.append(finding("body-size", "warn",
                                f"Body is ~{body_tokens} tokens (>{BODY_WARN_TOKENS}). Same concern."))
    if body_lines <= BODY_WARN_LINES and body_tokens <= BODY_WARN_TOKENS:
        findings.append(finding("body-size", "ok",
                                f"Body is {body_lines} lines / ~{body_tokens} tokens — within budget."))

    # --- weak pointers in the body ---
    for i, line in enumerate(body.splitlines(), 1):
        if POINTER_RE.search(line) and re.search(r"\b(see|refer to|check)\b", line, re.I) \
                and not CONDITION_WORDS.search(line):
            findings.append(finding("routing", "warn",
                                    f"Weak pointer (line {i}): a file reference with no WHEN condition "
                                    "reads as a footnote. Attach a trigger (read X *before* …, *if* …).",
                                    detail=line.strip()))

    # --- supporting folders ---
    for sub in ("scripts", "references", "assets"):
        present = os.path.isdir(os.path.join(path, sub))
        findings.append(finding("structure", "info",
                                f"{sub}/ {'present' if present else 'absent'}"))

    # --- reference file sizes + one-level-deep check ---
    ref_dir = os.path.join(path, "references")
    if os.path.isdir(ref_dir):
        for fn in sorted(os.listdir(ref_dir)):
            fp = os.path.join(ref_dir, fn)
            if not os.path.isfile(fp) or not fn.endswith((".md", ".txt")):
                continue
            with open(fp, encoding="utf-8", errors="replace") as rh:
                rtext = rh.read()
            rlines = rtext.count("\n") + 1
            has_toc = bool(re.search(r"table of contents|^## contents", rtext, re.I | re.M))
            if rlines > REF_TOC_LINES and not has_toc:
                findings.append(finding("references", "warn",
                                        f"references/{fn} is {rlines} lines (>{REF_TOC_LINES}) with no "
                                        "table of contents — add one so the agent can orient."))
            # chains: a reference that points at another reference
            if re.search(r"references/[\w-]+\.(md|txt)", rtext):
                findings.append(finding("references", "warn",
                                        f"references/{fn} points at another reference file. Keep routing "
                                        "one level deep — chains break in ways that are hard to debug."))

    summary = summarize(findings, name, folder)
    return summary, findings


def summarize(findings, name, folder):
    counts = {"error": 0, "warn": 0, "info": 0, "ok": 0}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    return {
        "skill": name or folder,
        "errors": counts["error"],
        "warnings": counts["warn"],
        "info": counts["info"],
        "ok": counts["ok"],
        "note": "Static checks only. A clean audit is NOT proof the skill works — "
                "run a paired eval (see references/eval-harness.md).",
    }


def print_text(summary, findings):
    order = {"error": 0, "warn": 1, "info": 2, "ok": 3}
    icon = {"error": "✗", "warn": "!", "info": "·", "ok": "✓"}
    print(f"\nskill-doctor · deterministic audit · {summary['skill']}")
    print("=" * 60)
    for f in sorted(findings, key=lambda x: order[x["severity"]]):
        print(f"  {icon[f['severity']]} [{f['check']}] {f['message']}")
        if "detail" in f:
            detail = f["detail"] if len(f["detail"]) < 200 else f["detail"][:197] + "…"
            print(f"      → {detail}")
    print("-" * 60)
    print(f"  {summary['errors']} errors · {summary['warnings']} warnings · "
          f"{summary['info']} info · {summary['ok']} ok")
    print(f"  {summary['note']}\n")


def main():
    ap = argparse.ArgumentParser(description="Deterministic static checks for a Claude Code skill.")
    ap.add_argument("path", help="path to the skill folder (containing SKILL.md)")
    ap.add_argument("--json", action="store_true", help="emit structured JSON instead of text")
    args = ap.parse_args()

    summary, findings = check_skill(args.path)
    if summary is None:
        # unreadable target — this IS a hard failure
        payload = {"summary": None, "findings": findings}
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            for f in findings:
                print(f"ERROR [{f['check']}] {f['message']}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps({"summary": summary, "findings": findings}, indent=2))
    else:
        print_text(summary, findings)
    sys.exit(0)


if __name__ == "__main__":
    main()
