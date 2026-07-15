#!/usr/bin/env python3
"""
eval.py — runnable paired evaluation for a Claude Code skill.

The only real measure of a skill is a paired eval: run realistic prompts with and
without the skill and measure two numbers SEPARATELY — trigger rate (did the
description fire the skill?) and pass rate (once it fired, was the output right?).
This automates the loop I was otherwise running by hand: it spawns fresh headless
Claude contexts (`claude -p`) as trigger judges and as with-skill vs baseline pass
agents, scores objective assertions, and reports the two rates.

It is dry by design: pass agents are told to emit the commands they WOULD run, and
the harness disallows Bash/Edit/Write so nothing can actually execute.

Usage:
    python3 eval.py <spec.json>              # run the eval
    python3 eval.py <spec.json> --plan       # print the calls; make NO claude calls
    python3 eval.py <spec.json> --workers 4 --json

Spec format (see examples/eval-reconcile.json):
    {
      "skill_path": "/abs/path/to/skill",     # folder with SKILL.md
      "decoys": [{"name": "...", "description": "..."}],   # optional sibling skills
      "runs": 3,
      "model": "claude-sonnet-4-6",
      "trigger": {"positive": ["..."], "negative": ["..."]},
      "pass": [{"prompt": "...", "assert": [{"desc": "...", "pattern": "regex"}]}]
    }
"""

import argparse
import concurrent.futures
import json
import os
import re
import subprocess
import sys

# Tools the headless agents may never use — enforces a dry run at the harness layer.
DRY_DISALLOW = ["Bash", "Edit", "Write", "NotebookEdit"]
DEFAULT_MODEL = "claude-sonnet-4-6"


# ---------- spec + skill loading -------------------------------------------------

def _read_skill(skill_path):
    smd = os.path.join(skill_path, "SKILL.md")
    with open(smd, encoding="utf-8") as fh:
        raw = fh.read()
    name = desc = None
    body = raw
    if raw.startswith("---"):
        end = raw.find("\n---", 3)
        if end != -1:
            fm = raw[3:end]
            body = raw[end + 4:].lstrip("\n")
            nm = re.search(r"^name:\s*(.+)$", fm, re.M)
            dm = re.search(r"description:\s*(.+(?:\n\s+.+)*)", fm)
            name = nm.group(1).strip() if nm else None
            desc = re.sub(r"\s+", " ", dm.group(1)).strip() if dm else None
    return name, desc, body


def load_spec(path):
    with open(path, encoding="utf-8") as fh:
        spec = json.load(fh)
    name, desc, body = _read_skill(spec["skill_path"])
    spec.setdefault("name", name)
    spec.setdefault("description", desc)
    spec["_body"] = body
    spec.setdefault("runs", 3)
    spec.setdefault("model", DEFAULT_MODEL)
    spec.setdefault("decoys", [])
    spec.setdefault("trigger", {})
    spec["trigger"].setdefault("positive", [])
    spec["trigger"].setdefault("negative", [])
    spec.setdefault("pass", [])
    return spec


# ---------- prompt construction --------------------------------------------------

def build_trigger_prompt(spec, user_msg):
    catalog = [f"- {spec['name']} — {spec['description']}"]
    for d in spec["decoys"]:
        catalog.append(f"- {d['name']} — {d['description']}")
    return (
        "You are Claude Code at the start of a session. Answer only from reasoning; "
        "do not use any tools.\n\n"
        "These skills are installed (name — description):\n"
        + "\n".join(catalog)
        + f"\n\nThe user's message:\n\"{user_msg}\"\n\n"
        "Which single installed skill, if any, would you invoke to handle this? If none "
        'applies, answer NONE. Respond with ONLY a JSON object: {"skill": "<name or NONE>"}. '
        "No other text."
    )


def build_pass_prompt(spec, user_msg, with_skill):
    if with_skill:
        head = (
            "You are Claude Code. You have this skill available:\n\n"
            f"--- SKILL: {spec['name']} ---\n{spec['_body']}\n--- END SKILL ---\n\n"
        )
    else:
        head = "You are Claude Code with no special project skill for this task.\n\n"
    return (
        head
        + f"The user says:\n\"{user_msg}\"\n\n"
        "Produce the exact commands or steps you would run to accomplish this"
        + (", following the skill" if with_skill else "")
        + ". DO NOT execute anything — output only what you would run."
    )


# ---------- scoring --------------------------------------------------------------

def score_assertions(text, assertions):
    return [{"desc": a["desc"], "ok": bool(re.search(a["pattern"], text, re.I | re.S))}
            for a in assertions]


def parse_skill_choice(text):
    m = re.search(r'"skill"\s*:\s*"([^"]*)"', text)
    if m:
        return m.group(1).strip()
    return text.strip().strip('"').splitlines()[0] if text.strip() else "NONE"


# ---------- the claude call ------------------------------------------------------

def call_claude(prompt, model):
    cmd = ["claude", "-p", prompt, "--output-format", "json", "--model", model,
           "--strict-mcp-config", "--disallowed-tools", *DRY_DISALLOW]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
    except subprocess.TimeoutExpired:
        return {"ok": False, "text": "", "cost": 0.0, "error": "timeout"}
    if proc.returncode != 0:
        return {"ok": False, "text": "", "cost": 0.0, "error": (proc.stderr or "")[:200]}
    try:
        d = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "text": proc.stdout[:200], "cost": 0.0, "error": "non-json output"}
    return {"ok": not d.get("is_error"), "text": d.get("result", ""),
            "cost": d.get("total_cost_usd") or 0.0, "error": d.get("api_error_status")}


# ---------- run phases -----------------------------------------------------------

def _run_jobs(jobs, workers):
    """jobs: list of (key, prompt, model). Returns {index: call_result}."""
    out = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(call_claude, p, m): i for i, (_, p, m) in enumerate(jobs)}
        for fut in concurrent.futures.as_completed(futs):
            out[futs[fut]] = fut.result()
    return out


def run_eval(spec, workers):
    jobs, meta = [], []

    # trigger jobs: each positive/negative prompt, `runs` times
    for polarity in ("positive", "negative"):
        for prompt in spec["trigger"][polarity]:
            for _ in range(spec["runs"]):
                jobs.append(("trigger", build_trigger_prompt(spec, prompt), spec["model"]))
                meta.append(("trigger", polarity, prompt))

    # pass jobs: each pass prompt, with-skill and baseline, `runs` times
    for pc in spec["pass"]:
        for arm in ("skill", "baseline"):
            for _ in range(spec["runs"]):
                jobs.append(("pass", build_pass_prompt(spec, pc["prompt"], arm == "skill"), spec["model"]))
                meta.append(("pass", arm, pc))

    results = _run_jobs(jobs, workers)

    # tally trigger
    trig = {"positive": {}, "negative": {}}
    for i, (kind, polarity, prompt) in enumerate(meta):
        if kind != "trigger":
            continue
        r = results[i]
        fired = r["ok"] and parse_skill_choice(r["text"]) == spec["name"]
        d = trig[polarity].setdefault(prompt, {"fired": 0, "runs": 0})
        d["runs"] += 1
        d["fired"] += int(fired)

    # tally pass
    passes = []
    for pc in spec["pass"]:
        passes.append({"prompt": pc["prompt"], "assert": pc.get("assert", []),
                       "skill": [], "baseline": []})
    idx_by_prompt = {pc["prompt"]: k for k, pc in enumerate(spec["pass"])}
    for i, (kind, arm, pc) in enumerate(meta):
        if kind != "pass":
            continue
        r = results[i]
        scored = score_assertions(r["text"], pc.get("assert", [])) if r["ok"] else []
        frac = (sum(s["ok"] for s in scored) / len(scored)) if scored else 0.0
        passes[idx_by_prompt[pc["prompt"]]][arm].append({"frac": frac, "scored": scored})

    cost = sum(r["cost"] for r in results.values())
    errors = sum(1 for r in results.values() if not r["ok"])
    return {"trigger": trig, "pass": passes, "cost": cost, "calls": len(jobs), "errors": errors}


# ---------- reporting ------------------------------------------------------------

def _rate(fired, runs):
    return f"{fired}/{runs}" + (f" ({100*fired//runs}%)" if runs else "")


def print_report(spec, res):
    print(f"\nskill-doctor · paired eval · {spec['name']}   (model: {spec['model']}, runs: {spec['runs']})")
    print("=" * 66)

    print("\nTRIGGER RATE — did the skill fire?  (positives want high, negatives want 0)")
    pos = res["trigger"]["positive"]
    neg = res["trigger"]["negative"]
    for prompt, d in pos.items():
        print(f"  + {_rate(d['fired'], d['runs']):<12} {prompt[:60]}")
    for prompt, d in neg.items():
        flag = "  ⚠ false fire" if d["fired"] else ""
        print(f"  - {_rate(d['fired'], d['runs']):<12} {prompt[:60]}{flag}")
    pf, pr = sum(d["fired"] for d in pos.values()), sum(d["runs"] for d in pos.values())
    nf, nr = sum(d["fired"] for d in neg.values()), sum(d["runs"] for d in neg.values())
    print(f"  → positives {_rate(pf, pr)} fired · negatives {_rate(nf, nr)} false-fired")

    print("\nPASS RATE — once loaded, was the output right?  (skill vs baseline)")
    for p in res["pass"]:
        def avg(arm):
            xs = [x["frac"] for x in p[arm]]
            return sum(xs) / len(xs) if xs else 0.0
        print(f"  • {p['prompt'][:60]}")
        print(f"      with skill: {avg('skill')*100:4.0f}%   baseline: {avg('baseline')*100:4.0f}%   "
              f"(Δ {(avg('skill')-avg('baseline'))*100:+.0f} pts)")
        # show which assertions the with-skill runs tended to miss
        misses = {}
        for run in p["skill"]:
            for s in run["scored"]:
                if not s["ok"]:
                    misses[s["desc"]] = misses.get(s["desc"], 0) + 1
        for desc, n in sorted(misses.items(), key=lambda x: -x[1]):
            print(f"        missed ({n}x): {desc}")

    print("-" * 66)
    print(f"  {res['calls']} calls · {res['errors']} errors · ${res['cost']:.2f}")
    print("  Trigger and pass are separate on purpose: a low number means different "
          "fixes\n  depending on which one it is (description vs body).\n")


def print_plan(spec):
    n_trig = (len(spec["trigger"]["positive"]) + len(spec["trigger"]["negative"])) * spec["runs"]
    n_pass = len(spec["pass"]) * 2 * spec["runs"]
    print(f"PLAN for {spec['name']} — model {spec['model']}, {spec['runs']} runs")
    print(f"  trigger calls: {n_trig}  ({len(spec['trigger']['positive'])} pos + "
          f"{len(spec['trigger']['negative'])} neg × {spec['runs']})")
    print(f"  pass calls:    {n_pass}  ({len(spec['pass'])} prompts × 2 arms × {spec['runs']})")
    print(f"  TOTAL claude -p calls: {n_trig + n_pass}")
    if spec["trigger"]["positive"]:
        print("\n--- sample trigger prompt ---")
        print(build_trigger_prompt(spec, spec["trigger"]["positive"][0])[:700])
    if spec["pass"]:
        print("\n--- sample pass (with-skill) prompt head ---")
        print(build_pass_prompt(spec, spec["pass"][0]["prompt"], True)[:400])


def main():
    ap = argparse.ArgumentParser(description="Runnable paired eval for a Claude Code skill.")
    ap.add_argument("spec", help="path to an eval spec JSON")
    ap.add_argument("--plan", action="store_true", help="print the calls and make NO claude calls")
    ap.add_argument("--workers", type=int, default=3, help="concurrent claude -p calls")
    ap.add_argument("--json", action="store_true", help="emit raw results as JSON")
    args = ap.parse_args()

    spec = load_spec(args.spec)
    if args.plan:
        print_plan(spec)
        return

    res = run_eval(spec, args.workers)
    if args.json:
        print(json.dumps(res, indent=2))
    else:
        print_report(spec, res)


if __name__ == "__main__":
    main()
