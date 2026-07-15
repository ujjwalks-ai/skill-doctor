#!/usr/bin/env python3
"""
iterate.py — the v3 loop: measure the gate, propose a description fix FROM the
observed trigger misses, re-measure, keep it only if it helps.

This closes the loop over audit.py (v1) and eval.py (v2). It deliberately only
touches the description and only re-measures TRIGGER rate, because that is the one
thing a description edit changes — pass rate is body-driven and untouched here.

Honesty guardrails (the book's warnings, in code):
  - Edits are DRAFTED from the eval's observed misses, never from imagination:
    the proposal prompt is handed the exact prompts the skill failed to fire on
    and the sibling skills it must stay disjoint from.
  - Every proposal is RE-MEASURED. A change is kept only if positives fire more
    AND no negative starts false-firing. Otherwise it is rejected and the loop
    stops.
  - Nothing is written to the skill. The winning description is staged to
    <skill>/SKILL.md.proposed for a human to review and apply.

Usage:
    python3 iterate.py <eval-spec.json> [--max-iters 2] [--workers 3]

The spec is the same format eval.py uses (skill_path, decoys, runs, trigger.*).
"""

import argparse
import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("skdeval", os.path.join(_HERE, "eval.py"))
ev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ev)


def measure_trigger(spec, description, workers):
    """Trigger rate for a given description, injected into the judge prompt — no
    disk write needed (trigger judging only reads name + description + decoys)."""
    s = {**spec, "description": description}
    jobs, meta = [], []
    for pol in ("positive", "negative"):
        for prompt in spec["trigger"][pol]:
            for _ in range(spec["runs"]):
                jobs.append(("t", ev.build_trigger_prompt(s, prompt), spec["model"]))
                meta.append((pol, prompt))
    results = ev._run_jobs(jobs, workers)
    per = {}
    for i, (pol, prompt) in enumerate(meta):
        r = results[i]
        fired = r["ok"] and ev.parse_skill_choice(r["text"]) == spec["name"]
        d = per.setdefault((pol, prompt), {"fired": 0, "runs": 0})
        d["runs"] += 1
        d["fired"] += int(fired)
    pos = {k: v for k, v in per.items() if k[0] == "positive"}
    neg = {k: v for k, v in per.items() if k[0] == "negative"}
    return {
        "per": per,
        "pos_fired": sum(v["fired"] for v in pos.values()),
        "pos_total": sum(v["runs"] for v in pos.values()),
        "neg_fired": sum(v["fired"] for v in neg.values()),
        "neg_total": sum(v["runs"] for v in neg.values()),
        "cost": sum(r["cost"] for r in results.values()),
    }


def failures(measurement):
    """The observed misses that ground the next edit."""
    missed = [p for (pol, p), v in measurement["per"].items()
              if pol == "positive" and v["fired"] < v["runs"]]
    false_fire = [p for (pol, p), v in measurement["per"].items()
                  if pol == "negative" and v["fired"] > 0]
    return missed, false_fire


def valid_description(d):
    return bool(d) and len(d) <= 1024 and "<" not in d and ">" not in d


def propose_description(spec, current, missed, workers=1):
    decoys = "\n".join(f"- {d['name']}: {d['description']}" for d in spec["decoys"]) or "(none)"
    negs = "\n".join(f"- {p}" for p in spec["trigger"]["negative"]) or "(none)"
    miss = "\n".join(f"- {p}" for p in missed) or "(none)"
    prompt = (
        f"You are improving ONLY the `description:` frontmatter of a Claude Code skill named "
        f"\"{spec['name']}\". The description is a matcher that decides whether the skill loads.\n\n"
        f"Current description:\n{current}\n\n"
        f"It currently FAILS to fire on these real requests (it SHOULD fire on them):\n{miss}\n\n"
        f"It must still NOT fire on these (they belong to a sibling skill or are out of scope):\n{negs}\n\n"
        f"Sibling skills it must stay disjoint from:\n{decoys}\n\n"
        "Rewrite the description so it fires on the missed requests: enumerate the trigger surface "
        "(the actual words and phrasings a user types, drawn from the missed requests), include a "
        "'Use this whenever …' clause, and add a one-line disambiguation versus the siblings if that "
        "helps keep them disjoint. Keep it under 1024 characters, no angle brackets. "
        "Output ONLY the new description text on a single line — no surrounding quotes, no 'description:' "
        "key, no explanation."
    )
    r = ev.call_claude(prompt, spec["model"])
    text = " ".join(r["text"].split()) if r["ok"] else None
    return text, (r["cost"] if r["ok"] else 0.0)


def stage_proposed(spec, description):
    name, _, body = ev._read_skill(spec["skill_path"])
    content = f"---\nname: {name}\ndescription: {description}\n---\n\n{body}"
    out = os.path.join(spec["skill_path"], "SKILL.md.proposed")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(content)
    return out


def run_iterate(spec, max_iters, workers):
    current = spec["description"]
    base = measure_trigger(spec, current, workers)
    best = base
    cost = base["cost"]
    history = [{"label": "baseline", "desc": current, "m": base, "kept": True}]

    for it in range(1, max_iters + 1):
        missed, false_fire = failures(best)
        if not missed and not false_fire:
            break  # converged
        cand_desc, pcost = propose_description(spec, current, missed, workers)
        cost += pcost
        if not valid_description(cand_desc):
            history.append({"label": f"iter {it}", "desc": cand_desc, "m": None,
                            "kept": False, "note": "invalid proposal"})
            break
        cand = measure_trigger(spec, cand_desc, workers)
        cost += cand["cost"]
        improved = cand["pos_fired"] > best["pos_fired"] and cand["neg_fired"] <= best["neg_fired"]
        history.append({"label": f"iter {it}", "desc": cand_desc, "m": cand,
                        "kept": improved,
                        "note": "" if improved else "no positive gain / negative regressed"})
        if improved:
            current, best = cand_desc, cand
        else:
            break

    return {"final_desc": current, "baseline": base, "best": best,
            "history": history, "cost": cost, "changed": current != spec["description"]}


def print_report(spec, res):
    def rate(m):
        return (f"positives {m['pos_fired']}/{m['pos_total']}"
                f" · negatives {m['neg_fired']}/{m['neg_total']} false-fired")
    print(f"\nskill-doctor · iterate · {spec['name']}   (model {spec['model']}, runs {spec['runs']})")
    print("=" * 66)
    for h in res["history"]:
        tag = "baseline" if h["label"] == "baseline" else f"{h['label']:<8} [{'kept' if h['kept'] else 'rejected'}]"
        line = rate(h["m"]) if h["m"] else "(invalid proposal)"
        print(f"  {tag}: {line}" + (f"  — {h.get('note')}" if h.get("note") else ""))
    print("-" * 66)
    b, f = res["baseline"], res["best"]
    print(f"  BEFORE: {rate(b)}")
    print(f"  AFTER : {rate(f)}")
    if res["changed"]:
        out = stage_proposed(spec, res["final_desc"])
        print(f"\n  Proposed description (staged to {out} — review, then apply):\n")
        print("    " + res["final_desc"])
    else:
        print("\n  No improving edit found — description unchanged.")
    print(f"\n  ${res['cost']:.2f}. Trigger only; pass rate is body-driven and untouched. "
          "Nothing written to the skill.\n")


def main():
    ap = argparse.ArgumentParser(description="v3 loop: propose a description fix from observed trigger misses and re-measure.")
    ap.add_argument("spec", help="eval spec JSON (same format as eval.py)")
    ap.add_argument("--max-iters", type=int, default=2)
    ap.add_argument("--workers", type=int, default=3)
    args = ap.parse_args()
    spec = ev.load_spec(args.spec)
    if not spec["trigger"]["positive"]:
        sys.exit("spec has no positive trigger prompts to optimize against")
    res = run_iterate(spec, args.max_iters, args.workers)
    print_report(spec, res)


if __name__ == "__main__":
    main()
