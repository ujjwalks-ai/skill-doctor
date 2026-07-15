# The paired eval — the only real test

Static audit tells you a skill is well-formed. It cannot tell you the skill
helps. For that you need a paired evaluation, and there is no substitute for it.
This file is the method skill-doctor hands you at the end of every report.

## The whole idea

Run the same prompt twice — once with the skill installed, once without — several
times each, and compare. The baseline (the "without" run) is the only thing that
isolates *the skill's* contribution from the model's own competence.

Two baselines, depending on what you are doing:

- **New skill** → baseline is *no skill at all*.
- **Improving a skill** → baseline is the *old version, actually run* (snapshot it
  before editing). "It feels better" is the most expensive sentence in this
  field; run the old version instead of remembering it.

Why it is not optional: in SkillsBench, curated skills lifted pass rate ~16
points on average — but 16 of 84 tasks came out **worse** with the skill than
without. A degraded skill looks exactly like a mediocre answer, and the instinct
to "add detail" makes it worse. Without a baseline you cannot tell a harmful
skill from an insufficient one, and the fixes are opposites.

## Measure two numbers, never one

| Metric | Question | What breaks it | Fix lives in |
|---|---|---|---|
| **Trigger rate** | Did the skill load at all? | the description | rubric §1 |
| **Pass rate** | Once loaded, was the output right? | the body | rubric §2 |

Report them separately: *"fired on 9/10; of those 9, 7 were correct."* A single
aggregate ("40%") cannot distinguish a broken gate + excellent body from a fine
gate + broken body — opposite diagnoses, opposite fixes. **Check triggering
first**: if it never fired, pass rate measures a file that never entered the
conversation.

## The prompts

- **Write them the way you actually type.** "What was MAU last quarter", not "use
  the warehouse skill to compute MAU" — naming the skill removes the whole
  problem.
- **Include negatives** — prompts that should *not* fire the skill. A skill that
  fires on everything is as broken as one that fires on nothing.
- **Avoid trivial prompts** the model handles alone regardless ("read this CSV").
  They test nothing and will make a fine description look terrible.
- **Run each 3+ times.** Triggering is stochastic; one run is an anecdote with a
  number attached.

## Assertions — make "correct" objective

Write yes/no checks two people would grade identically; script them where you can.

- Works: "used `run_metric` not `execute_sql`", "resolved the quarter to fiscal
  not calendar", "called `verify_metric` before presenting".
- Does not work: "the output is clear and professional" — an opinion in a lab
  coat. Clarity matters, which is exactly why it deserves honest human review, not
  a fake pass/fail.

Split honestly: assert the objective half (tool choice, dates, verification,
structure), eyeball the subjective half (tone, framing) deliberately, and never
confuse which is which.

## The loop

```
1. Find the failure   run WITHOUT the skill; read transcripts; write down what broke
2. Draft              target those failures, nothing else
3. Paired eval        with skill and against the baseline
4. Review             trigger rate, pass rate, and the transcripts (not just numbers)
5. Rewrite            usually by cutting
6. Repeat
7. Scale              get the shape right on 3 cases, then expand to ~20
```

Step 1 is the one everyone skips, and it is the whole thing: a skill written from
imagination corrects failures the model was not having and misses the ones it
was. Do not ask the model to write its own skill from scratch — self-generated
skills scored *below zero* in SkillsBench, because the model has never watched
itself fail. Use it to draft *from* an observed failure list, and to grade
transcripts. Not as the source of truth about what it gets wrong.

## The one-hour version

Five prompts, three runs each, with and without the skill. Thirty runs. Record
whether it fired and whether the assertions passed. You now have two numbers with
error bars and a set of transcripts to read — a defensible answer to whether the
work was worth anything. Everything more elaborate is an optimisation of this
loop, not a replacement for it.
