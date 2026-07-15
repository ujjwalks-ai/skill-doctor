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
# A "read this doc" pointer — reference documentation the agent is told to read.
# Deliberately limited to doc extensions: a script or asset invocation
# (`python3 scripts/x.py …`) is a command to run, not a footnote to read, and
# must never be flagged as a weak pointer.
DOC_POINTER_RE = re.compile(r"(references/|\./)?[\w./-]+\.(md|txt|rst)\b")
# A pointer that is really a command being run, not a document being read.
EXEC_CONTEXT_RE = re.compile(r"\b(python3?|node|deno|bash|sh|ruby|npx|pnpm|yarn)\b|(\./)")
# Verbs that introduce a *passive footnote* pointer ("see X.md", "refer to X").
# An imperative "Read X.md" is a directive, not a footnote, so it is not flagged;
# the smell this catches is the optional-sounding aside with no trigger.
POINTER_VERB_RE = re.compile(r"\b(see|refer to)\b", re.I)
# Phrasings that turn a pointer from a footnote into a trigger — a WHEN clause
# ("before …", "if …") or a purpose clause ("to debug …", "to understand …").
CONDITION_WORDS = re.compile(
    r"\b(before|after|if|when|whenever|unless|while|once|for any|for each|"
    r"to (understand|debug|find|resolve|investigate|diagnose|trace|see|check|know|learn|get|dig))\b",
    re.I,
)

# --- Secret / credential detection -------------------------------------------
# A hardcoded credential in a skill leaks the moment the folder is shared,
# committed, or synced. High-confidence formats are errors; generic key=value
# assignments are warnings (more false-positive prone). Matched values are
# always redacted in the output so the report never re-echoes the secret.
HIGH_CONFIDENCE_SECRETS = [
    ("Slack incoming webhook", re.compile(r"https://hooks\.slack\.com/services/[A-Za-z0-9_/+-]+")),
    ("AWS access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[posru]_[A-Za-z0-9]{30,}\b")),
    ("GitLab PAT", re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("Stripe live key", re.compile(r"\b[sr]k_live_[0-9a-zA-Z]{16,}\b")),
    ("OpenAI-style key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("Slack API token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("private key block", re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----")),
    ("JSON Web Token", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{6,}\b")),
    ("credentials in URL", re.compile(r"\b[a-z][a-z0-9+.\-]*://[^/\s:@]+:[^/\s@]{3,}@")),
]
GENERIC_SECRET = re.compile(
    r"(?i)\b(api[_-]?key|secret|token|password|passwd|pwd|access[_-]?key|client[_-]?secret)\b"
    r"\s*[:=]\s*[\"']?([A-Za-z0-9/_+.\-]{16,})[\"']?"
)
# Values that are obviously placeholders, not real secrets.
PLACEHOLDER_RE = re.compile(
    r"(?i)(your|example|redacted|placeholder|changeme|dummy|sample|xxxx|\.\.\.|"
    r"<[^>]+>|\$\{?[a-z_][a-z0-9_]*\}?|foo|bar)"
)
# File types worth scanning for secrets (text only).
TEXT_EXTS = {".md", ".txt", ".rst", ".py", ".sh", ".bash", ".zsh", ".json",
             ".yaml", ".yml", ".env", ".cfg", ".ini", ".toml", ""}

# Fenced code blocks whose language means "runnable" — candidates for scripts/.
CODE_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})\s*([A-Za-z0-9_+-]*)\s*$")
EXEC_LANGS = {"bash", "sh", "shell", "zsh", "console", "shell-session",
              "python", "py", "python3"}

# For repo-level trigger-overlap: significant words in a description.
STOPWORDS = frozenset(
    "the a an to of for and or use used when this that with any all into onto "
    "any use invoke asked ask user users about via them then than only just "
    "you your it its is are be do does after before if whenever while once".split()
)


def finding(check, severity, message, detail=None):
    """severity: error | warn | info | ok"""
    f = {"check": check, "severity": severity, "message": message}
    if detail is not None:
        f["detail"] = detail
    return f


def scan_embedded_code(body):
    """Flag inline bash/python that should live in scripts/. Deterministic code
    embedded in the body is re-assembled by the model every run and can't be
    tested — the reconcile/deploy footgun. Conservative on purpose: only
    executable-language fences count, so example JSON/yaml never trips it."""
    blocks, fence, lang, count = [], None, None, 0
    for line in body.splitlines():
        m = CODE_FENCE_RE.match(line)
        if fence is None and m:
            fence, lang, count = m.group(1)[0], (m.group(2) or "").lower(), 0
        elif fence is not None and m and m.group(1)[0] == fence:
            blocks.append((lang, count))
            fence = None
        elif fence is not None:
            count += 1

    exec_blocks = [(l, n) for l, n in blocks if l in EXEC_LANGS]
    total = sum(n for _, n in exec_blocks)
    biggest = max((n for _, n in exec_blocks), default=0)
    n = len(exec_blocks)

    if biggest >= 20 or total >= 50:
        reasons = []
        if biggest >= 20:
            reasons.append(f"a single {biggest}-line block")
        if total >= 50:
            reasons.append(f"~{total} lines across {n} blocks")
        return [finding("embedded-code", "warn",
                        f"Inline executable code ({'; '.join(reasons)}) — deterministic steps belong in "
                        "scripts/, not prose: the model re-assembles them each run and they can't be "
                        "tested. Extract to a script the body routes to; keep the prose as the 'why'.")]
    if total >= 25 and n >= 4:
        return [finding("embedded-code", "info",
                        f"~{total} lines of inline executable code across {n} blocks looks like a "
                        "procedure. Consider moving the deterministic parts to scripts/.")]
    return [finding("embedded-code", "ok",
                    "No heavy inline code — the body isn't carrying a script.")]


def scan_secrets(path):
    """Walk the skill's text files for hardcoded credentials. Secrets are redacted
    in the returned findings so the report never re-echoes them."""
    findings = []
    # Skip dev/VCS dirs that aren't part of the skill surface (SKILL.md +
    # scripts/references/assets). Notably `tests/` may hold secret-shaped
    # fixtures by design.
    skip_dirs = {".git", "__pycache__", "node_modules", "tests", "test",
                 ".pytest_cache", ".venv", "venv", "dist", "build"}
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for fn in sorted(files):
            if os.path.splitext(fn)[1].lower() not in TEXT_EXTS:
                continue
            fp = os.path.join(root, fn)
            try:
                with open(fp, encoding="utf-8") as fh:
                    text = fh.read()
            except (UnicodeDecodeError, OSError):
                continue
            rel = os.path.relpath(fp, path)
            for i, line in enumerate(text.splitlines(), 1):
                hc_hit = False
                for label, pat in HIGH_CONFIDENCE_SECRETS:
                    m = pat.search(line)
                    if m and "EXAMPLE" not in m.group(0).upper():
                        hc_hit = True
                        findings.append(finding(
                            "secret", "error",
                            f"Hardcoded {label} in {rel}:{i} — a credential in a skill leaks when the "
                            "folder is shared, committed, or synced. Move it to an env var / secret "
                            "and rotate it.",
                            detail=line.replace(m.group(0), "«REDACTED»").strip()[:160]))
                if not hc_hit:
                    gm = GENERIC_SECRET.search(line)
                    if gm and not PLACEHOLDER_RE.search(gm.group(2)):
                        findings.append(finding(
                            "secret", "warn",
                            f"Possible hardcoded {gm.group(1).lower()} in {rel}:{i}. If it is a real "
                            "credential move it to an env var; if a placeholder, ignore.",
                            detail=line.replace(gm.group(2), "«REDACTED»").strip()[:160]))
    return findings


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
    # A weak pointer is a documentation reference the agent is told to read with
    # no WHEN/purpose clause. Command invocations (`python3 scripts/x.py …`) and
    # non-doc files are commands, not read-pointers, so they are excluded.
    for i, line in enumerate(body.splitlines(), 1):
        if (DOC_POINTER_RE.search(line)
                and POINTER_VERB_RE.search(line)
                and not CONDITION_WORDS.search(line)
                and not EXEC_CONTEXT_RE.search(line)):
            findings.append(finding("routing", "warn",
                                    f"Weak pointer (line {i}): a documentation reference with no WHEN "
                                    "condition reads as a footnote. Attach a trigger (read X *before* …, "
                                    "*if* …, *to debug* …).",
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

    # --- embedded-code check (should this be a script?) ---
    findings.extend(scan_embedded_code(body))

    # --- secret / credential scan (whole skill folder) ---
    findings.extend(scan_secrets(path))

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


def _load_meta(skill_md_path):
    try:
        with open(skill_md_path, encoding="utf-8", errors="replace") as fh:
            fm, _ = parse_frontmatter(fh.read())
    except OSError:
        return None, None
    fm = fm or {}
    return fm.get("name"), fm.get("description")


def discover_skills(repo):
    """Find skills at the top level of a repo: `<dir>/SKILL.md` folder skills and
    loose `<name>.md` files carrying skill frontmatter (the stale-copy pattern)."""
    skills = []
    for entry in sorted(os.listdir(repo)):
        full = os.path.join(repo, entry)
        if os.path.isdir(full):
            smd = os.path.join(full, "SKILL.md")
            if os.path.isfile(smd):
                name, desc = _load_meta(smd)
                skills.append({"name": name or entry, "kind": "folder",
                               "path": full, "basename": entry, "description": desc or ""})
        elif entry.endswith(".md") and entry != "SKILL.md":
            name, desc = _load_meta(full)
            if name and desc:  # frontmatter with name+description → a loose skill file
                skills.append({"name": name, "kind": "loose", "path": full,
                               "basename": entry[:-3], "description": desc})
    return skills


def _trigger_tokens(desc):
    return {w for w in re.findall(r"[a-z][a-z0-9-]{2,}", desc.lower()) if w not in STOPWORDS}


def cross_checks(skills):
    findings = []

    # 1. Duplicate name — the loader cannot disambiguate.
    by_name = {}
    for s in skills:
        by_name.setdefault(s["name"], []).append(s)
    for name, group in sorted(by_name.items()):
        if len(group) > 1:
            locs = ", ".join(f"{g['kind']}:{g['basename']}" for g in group)
            findings.append(finding("duplicate-name", "error",
                                    f"{len(group)} skills share name '{name}' ({locs}) — the loader "
                                    "cannot disambiguate. Keep one; rename or delete the rest."))

    # 2. Loose file shadowing a folder skill — usually a superseded copy.
    folder_keys = {s["basename"] for s in skills if s["kind"] == "folder"} | \
                  {s["name"] for s in skills if s["kind"] == "folder"}
    for s in skills:
        if s["kind"] == "loose" and (s["basename"] in folder_keys or s["name"] in folder_keys):
            findings.append(finding("shadow-copy", "warn",
                                    f"Loose file {s['basename']}.md shadows a folder skill of the same "
                                    "name — likely a superseded copy. Confirm which is current and "
                                    "remove the stale one."))

    # 3. Highly overlapping trigger surfaces — may compete to fire.
    toks = [(s, _trigger_tokens(s["description"])) for s in skills]
    for i in range(len(toks)):
        for j in range(i + 1, len(toks)):
            (sa, ta), (sb, tb) = toks[i], toks[j]
            if sa["name"] == sb["name"] or not ta or not tb:
                continue
            inter, union = ta & tb, ta | tb
            jac = len(inter) / len(union) if union else 0
            if jac >= 0.5:
                findings.append(finding("trigger-overlap", "info",
                                        f"'{sa['name']}' and '{sb['name']}' overlap {int(jac*100)}% on "
                                        f"trigger words ({', '.join(sorted(inter)[:6])}). A bare request "
                                        "may load either — ensure a distinguishing word separates them."))
    return findings


def audit_repo(repo):
    if not os.path.isdir(repo):
        return None, [finding("target", "error", f"Not a directory: {repo}")]
    skills = discover_skills(repo)
    per_skill = []
    for s in skills:
        if s["kind"] == "folder":
            summ, _ = check_skill(s["path"])
            errs = summ["errors"] if summ else 1
            warns = summ["warnings"] if summ else 0
        else:
            errs = warns = 0  # loose files are covered by the cross-checks
        per_skill.append({"name": s["name"], "kind": s["kind"],
                          "path": os.path.relpath(s["path"], repo),
                          "errors": errs, "warnings": warns})
    cross = cross_checks(skills)
    summary = {
        "repo": repo,
        "skills": len(skills),
        "cross_errors": sum(1 for f in cross if f["severity"] == "error"),
        "cross_warnings": sum(1 for f in cross if f["severity"] == "warn"),
        "skill_errors": sum(p["errors"] for p in per_skill),
        "skill_warnings": sum(p["warnings"] for p in per_skill),
    }
    return summary, {"per_skill": per_skill, "cross_findings": cross}


def print_repo_text(summary, payload):
    icon = {"error": "✗", "warn": "!", "info": "·", "ok": "✓"}
    order = {"error": 0, "warn": 1, "info": 2, "ok": 3}
    print(f"\nskill-doctor · repo audit · {summary['repo']}")
    print("=" * 60)
    print(f"{summary['skills']} skills found\n")
    print("Cross-skill findings:")
    cross = sorted(payload["cross_findings"], key=lambda x: order[x["severity"]])
    if cross:
        for f in cross:
            print(f"  {icon[f['severity']]} [{f['check']}] {f['message']}")
    else:
        print("  ✓ none")
    print("\nPer-skill:")
    for p in sorted(payload["per_skill"], key=lambda x: (-x["errors"], -x["warnings"], x["name"])):
        flag = "" if (p["errors"] or p["warnings"]) else " ✓"
        print(f"  {p['name']:<28} {p['kind']:<7} {p['errors']} err · {p['warnings']} warn{flag}")
    print("-" * 60)
    print(f"  cross: {summary['cross_errors']} err · {summary['cross_warnings']} warn   "
          f"skills: {summary['skill_errors']} err · {summary['skill_warnings']} warn")
    print("  Static checks only — run paired evals for the skills that matter.\n")


def main():
    ap = argparse.ArgumentParser(description="Deterministic static checks for a Claude Code skill.")
    ap.add_argument("path", help="path to a skill folder, or a directory of skills with --repo")
    ap.add_argument("--json", action="store_true", help="emit structured JSON instead of text")
    ap.add_argument("--repo", action="store_true",
                    help="treat PATH as a directory of skills: run cross-skill checks + audit each")
    args = ap.parse_args()

    if args.repo:
        summary, payload = audit_repo(args.path)
        if summary is None:
            if args.json:
                print(json.dumps({"summary": None, "findings": payload}, indent=2))
            else:
                for f in payload:
                    print(f"ERROR [{f['check']}] {f['message']}", file=sys.stderr)
            sys.exit(1)
        if args.json:
            print(json.dumps({"summary": summary, **payload}, indent=2))
        else:
            print_repo_text(summary, payload)
        sys.exit(0)

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
