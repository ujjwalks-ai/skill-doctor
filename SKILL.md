---
name: skill-doctor
description: >-
  Evaluates a Claude Code skill and prescribes concrete fixes. Runs deterministic
  static checks on a SKILL.md and its scripts/references/assets, then applies the
  judgment rubric from The Art of Writing Skills to report what is wrong, what is
  missing, and exactly what to change. Use this whenever the user wants to
  evaluate, audit, review, critique, grade, improve, fix, or sanity-check a skill
  or a SKILL.md file, asks why a skill is not firing or not helping, or asks
  whether something should be a skill at all — even if they do not use the word
  "audit".
---

# skill-doctor

Diagnose a skill, then prescribe fixes. Work in four steps. Do not skip step 1,
and do not skip the caveat in step 4.

## Step 1 — Run the deterministic checks

The computable checks are exact and repeatable, so run them rather than eyeballing
them. From this skill's folder:

```
python3 scripts/audit.py <path-to-target-skill> --json
```

Read the JSON. `findings[]` carries `check`, `severity` (error | warn | info |
ok), `message`, and sometimes `detail`. Treat every `error` and `warn` as
something to address; `info` items (especially on `description`) are handed to
you as judgment prompts for step 2.

## Step 2 — Apply the judgment rubric

Read `references/rubric.md` and evaluate the things a script cannot. In order of
leverage:

1. **Shape.** Should this even be a skill? If it is patching an ambiguous tool,
   the fix belongs in the MCP layer. If it fires once in a blue moon, it is a
   prompt. If the problem is a noisy context rather than a wrong answer, it is a
   subagent. Say so plainly if the shape is wrong — no body edit rescues a
   mis-shaped skill.
2. **Description (the gate).** The script measured its length; you judge its
   content. Does it state both *what it does* and *when to use it*? Does the
   "when" enumerate the words the user would actually type, not a clean summary?
   Is it pushy? Does it close the escape hatch ("even if …")? A broken gate means
   the body never loads, so fix this before anything in the body.
3. **Body (the delta).** For each instruction ask: *would the model have done
   this anyway?* If yes, recommend cutting it. Check that specificity matches
   fragility (rigid for one-correct-way steps, loose for judgment calls) and that
   rules explain *why* rather than stacking bare MUSTs.

## Step 3 — Write the report

Structure it exactly like this:

- **Verdict** — one paragraph: does it fire, does it help, is the shape right?
- **Findings** grouped as *Shape · Description · Body · Structure*. Each finding:
  **severity** — **what** — **why** (name the principle) — **fix** (a concrete
  edit, not "improve this").
- **What's missing** — checks with no evidence, deterministic steps still written
  as prose that should be scripts, a trigger surface that omits obvious phrasings.

Order findings by leverage: shape, then description, then body, then structure.

## Step 4 — Hand off to a paired eval (required)

End every report with this, and mean it: **a clean static audit is not proof the
skill works.** The only real measure is a paired evaluation — the same prompt
with and without the skill, several runs each, measuring trigger rate and pass
rate separately. Read `references/eval-harness.md` and generate, for the target:

- **5 candidate trigger prompts** written the way the user actually types
  (positives that should fire the skill), plus **2 negatives** that should not.
- **A starter assertion list** — objective, yes/no checks on the output.

Present these so the user can run the real test next. Do not claim the skill is
good on the strength of the static audit alone.
