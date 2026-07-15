# Example report: `sample-skill`

This is the report skill-doctor produces for `examples/sample-skill/` — the
deterministic audit (from `scripts/audit.py`) combined with the judgment rubric.
It is here to show the shape of a good report, not as a template to fill in
mechanically.

---

## Verdict

The skill will **under-fire and, when it fires, mostly restate things the model
already knows.** The description is a bare summary with no trigger surface, so
the gate is the first problem. The body is half filler (a definition of CSV, a
definition of "report") and half deterministic arithmetic that should be a
script rather than prose. The shape is arguably wrong: much of what remains is
generic enough that the model would do it unaided.

## Findings

### Shape

- **warn — most of this is not a delta.** Reading a CSV, summing a column, and
  formatting a Markdown table are all things the model does unaided. *Why:* a
  skill earns its keep only as a correction to defaults. *Fix:* keep only the
  genuinely company-specific rules (the approved columns, the exact output
  contract) and consider whether what's left justifies a skill at all versus a
  short prompt.

### Description

- **warn — no trigger surface (26 chars).** "Utilities for CSV reports" says
  *what* but never *when*, and enumerates none of the words a user would type.
  *Why:* the description is a matcher; if it doesn't match the request, the body
  never loads. *Fix:*
  `Builds summary reports from CSV files — totals, growth rates, formatted tables.
  Use this whenever the user asks to summarise, total, or report on a CSV or
  spreadsheet, mentions growth rate or a totals table, or hands you a .csv to
  turn into a report — even if they don't say "report".`
- **info — not pushy, no escape hatch.** *Fix:* keep the "Use this whenever …"
  imperative and the "even if they don't say report" closer shown above.

### Body

- **warn — filler that fails the delta test.** The CSV definition and the
  "reports summarise data" sentence are things the model already knows. *Fix:*
  delete both paragraphs.
- **warn — deterministic arithmetic as prose.** The growth-rate formula is a
  computable step written in English, so the model re-derives it (and can slip)
  every run. *Why:* a script is the only part of a skill that doesn't vary.
  *Fix:* move it to `scripts/growth.py` and route to it: "compute growth with
  `python3 scripts/growth.py --current X --previous Y`".
- **warn — bare imperatives.** The closing "ALWAYS/NEVER" stack encodes a rigid
  output contract but explains nothing. The rigidity is *correct* here (output
  format is fragile), but *Fix:* replace the shouting with the actual template
  and one line of why ("downstream parsing depends on the totals row being
  bolded").

### Structure

- **warn — weak pointer (line 19).** "see references/columns.md for more detail"
  is a footnote. *Fix:* "resolve the column against `references/columns.md`
  *before* computing any total."
- **warn — reference chain.** `columns.md` points at `formulas.md`. *Why:* chains
  break invisibly. *Fix:* inline the one growth formula, or point the body
  directly at both files.
- **info — no `scripts/`.** Expected to change once the growth formula moves to
  code.

## What's missing

- A `scripts/` directory — the one deterministic step (growth) is currently prose.
- A trigger surface in the description (the single highest-leverage gap).
- The actual output template — it is asserted ("this exact structure") but never
  shown.

## Run the real test (paired eval)

**This static audit is not proof the skill works.** Run these next (see
`references/eval-harness.md`), 3× each, with and without the skill, and record
trigger rate and pass rate separately.

Positive prompts (should fire):

1. "Summarise this sales CSV into a report with totals."
2. "What's the growth rate on revenue between these two months?" (+ a CSV)
3. "Turn this spreadsheet export into a markdown table with a totals row."
4. "Give me a report off `q3.csv`."
5. "Total up the numeric columns in this file and format it."

Negative prompts (should NOT fire):

1. "What does CSV stand for?"
2. "Read this CSV and tell me the third row." (trivial; model handles it alone)

Starter assertions (objective):

- Used the approved column list from `references/columns.md`.
- Computed growth as `(current - previous) / previous * 100`, rounded to 1 dp.
- Output has a bolded totals row and every required section.
