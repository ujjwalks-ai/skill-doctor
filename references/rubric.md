# The judgment rubric

The half a script cannot grade. Read this after `scripts/audit.py` has run;
apply it in the order below, because the order is the leverage.

## Contents

- [0. Shape — is this even a skill?](#0-shape)
- [1. Description — the gate](#1-description)
- [2. Body — the delta](#2-body)
- [3. Structure — scripts, references, assets](#3-structure)
- [How to phrase a fix](#how-to-phrase-a-fix)

## 0. Shape

Before grading the writing, confirm a skill is the right mechanism at all. A
mis-shaped skill cannot be fixed by editing its body.

- **Should be an MCP fix.** The skill is compensating for an ambiguous or buggy
  tool ("remember, this tool returns empty on a bad table"). Fix the tool
  instead — every model and harness benefits, including the ones that never load
  the skill.
- **Should be a prompt.** It encodes a genuine one-off. A skill used once is
  worse than a prompt used once: it also costs standing metadata and upkeep.
  Heuristic: if you have not explained this thing three times, it is not a skill
  yet.
- **Should be a subagent.** The complaint is a noisy context, not a wrong answer.
  Isolation, not knowledge, is the fix. But if the token burn comes from taking
  the *wrong path* (hand-rolling what a tool does directly), that is a knowledge
  gap and a skill is right.

If the shape is wrong, say so as the headline finding and stop grading the rest
as though it were fine.

## 1. Description

The gate. If it does not match what the user typed, the body never loads and the
skill is silently absent. Iterate here before touching the body.

Grade against five questions:

1. **Both halves?** It must say *what it does* **and** *when to use it*. Most
   descriptions have only the first. The "when" is the load-bearing half.
2. **Trigger surface, not summary?** The "when" clause should enumerate the words
   that appear in real requests — the concrete nouns and phrasings the user
   types — not an elegant abstraction of the skill's purpose. Be shamelessly
   literal and slightly repetitive; this is a matcher, not documentation.
3. **Pushy?** The model under-fires skills because it believes it can handle
   things itself. "Use this whenever …" as an imperative beats an accurate label.
   Accuracy is not insistence.
4. **Escape hatch closed?** A clause like "even if they do not explicitly ask for
   X" pre-empts the model's "this looks simple, I've got it" reasoning. This
   clause does the most work.
5. **Clean?** ≤ 1024 chars, no angle brackets. Use the room — almost nobody does.

Caveat: pushiness only helps on substantive tasks. It will not (and should not)
force firing on trivial requests the model handles alone. Do not recommend
fighting that.

## 2. Body

Every line faces one test:

> Would the model have done this anyway? If yes, cut it.

The body is a correction, not documentation. Apply these lenses:

- **Delta, not filler.** Generic definitions ("MAU measures unique users…"),
  restated tool docs, and background facts the model already knows are filler.
  Cut them — they bury the load-bearing lines and lengthen the context.
- **Novel ≠ behaviour-changing.** A true, company-specific fact that changes no
  decision still does not belong. It earns a place only when rewritten to drive
  an action ("syncs nightly, so today's data is absent — say so, don't return
  yesterday's").
- **Less is more, measured.** Focused skills (≤ ~3 modules) beat comprehensive
  ones — not just cheaper, *better*. Bloated skills can be net-negative. When a
  body is growing, that is a signal to split or cut, not licence to keep writing.
- **Specificity matches fragility.** Fragile tasks (one correct way, fails
  silently — tool-call order, date ranges, file formats, verification) get rigid,
  numbered, "always" instructions. Flexible tasks (many good answers, need
  judgment — tone, framing, what to lead with) get loose goals with room. Rigid
  where you should be loose reads like a form letter; loose where you should be
  rigid is a bug with nice prose.
- **Explain why.** "Use `run_metric`; `execute_sql` bypasses the semantic layer,
  so the number won't match the dashboard" generalises to cases you never
  enumerated. A bare "always use `run_metric`" does not. Stacks of capitalised
  MUSTs are a smell — they feel authoritative and encode nothing.

When a skill underperforms, the default fix is to **cut**, not add. Check, in
order: did it fire (description), is it bloated (body) — and only then consider
that content is missing.

## 3. Structure

- **Scripts run; references are read; assets land in output.** Anything you can
  express as code, express as code — a script is the only part of a skill that
  does not vary between runs or between models. Deterministic prose (validation,
  date resolution, formatting, comparison against a source of truth) written into
  the body is a finding: recommend moving it to `scripts/`.
- **Split references on mutually exclusive branches.** If a task needs file A it
  usually does not need file B; separate files mean the agent pays for one, not
  both. Organise by variant, not by topic.
- **Route one level deep, with a condition.** The body points at a file *and says
  when to read it*. "See `X.md`" is a footnote; "read `X.md` before constructing
  a date range" is a trigger. References should not point at further references.
- **Script output is the interface.** A script that prints `False` tells the
  model nothing; `MISMATCH: mau 184,320 vs canonical 181,004 (delta 3,316)` tells
  it what happened. The source is invisible to the model — design the output for a
  reader who cannot see the code.

## How to phrase a fix

Every recommendation must be a concrete edit, not an opinion.

- Bad: "the description could be stronger."
- Good: "add a trigger clause: `Use this whenever the user mentions reconciling,
  match rates, QB vs Cube totals, or asks why totals differ — even if they don't
  say 'reconcile'.`"

Tie each fix to the principle it serves, so the reasoning travels to cases you
did not list.
