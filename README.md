# skill-doctor

**Diagnose a Claude Code skill and prescribe fixes.** Point it at a skill
folder; it audits the `SKILL.md` (and its `scripts/`, `references/`, `assets/`)
against the principles in *The Art of Writing Skills*, tells you **what's wrong
and what's missing**, and recommends **concrete edits**.

skill-doctor is itself a skill. It runs deterministic checks as code and applies
the judgment checks with the model — the same "express as code what you can"
split it grades other skills on.

## The one thing to understand first

A clean static audit is **not** proof that a skill works.

The only real measure of a skill is a *paired evaluation*: run the same prompt
with and without the skill, several times each, and measure two separate
numbers — **trigger rate** (did the description fire the skill at all?) and
**pass rate** (once loaded, was the output right?). A model reading its own
skill and declaring it good is the exact failure mode that makes
self-generated skills score *worse* than no skill at all.

So skill-doctor's job is the **shallow half**: catch the mechanical and
structural mistakes cheaply, and point out likely body/description problems —
then hand you the materials to run the real test. Every report ends with a
generated set of candidate trigger prompts and starter assertions so you can go
run the paired eval next (see `references/eval-harness.md`).

## What it checks

Deterministic (in `scripts/audit.py`, exact and repeatable):

- Frontmatter present and parseable; `name` and `description` exist
- `name` matches the folder, is lowercase/digits/hyphens, ≤ 64 chars
- `description` ≤ 1024 chars, flagged if too short to carry a trigger surface,
  and free of angle brackets (which can inject structure into the system prompt)
- Body size — warns past ~500 lines / ~5k tokens (bloat dilutes the load-bearing
  lines)
- Reference files — size, and whether a long one needs a table of contents
- Routing depth — references that point to other references (chains break)
- Weak pointers — "see `X.md`" with no *when* condition attached
- Embedded code — large inline bash/python blocks that should be extracted to a
  script the body routes to (the reconcile/deploy footgun)
- Presence of `scripts/`, `references/`, `assets/`
- Hardcoded secrets — Slack webhooks, AWS/GitHub/GitLab/Google/Stripe/OpenAI
  keys, private-key blocks, JWTs, credentials-in-URLs (error); generic
  `key = value` credentials (warn). Matched values are redacted in the report;
  localhost URLs, code/attribute references, and placeholders are not flagged.
- Portability — hardcoded operator/home paths (`/Users/…`, `/home/…`) that break
  when a teammate runs the skill (info)

Judgment (guided by `references/rubric.md`):

- **Shape** — should this even be a skill, or is it really an MCP fix, a one-off
  prompt, or a subagent?
- **Description as a gate** — does it say both *what it does* **and** *when to
  use it*, enumerate the words you'd actually type, read as pushy, and close the
  escape hatch?
- **Body as a delta** — does it correct the model's defaults, or restate things
  the model already knows? Is specificity matched to fragility? Does it explain
  *why* rather than stacking bare MUSTs?

## Install

Clone, then symlink into your Claude Code skills directory:

```bash
git clone git@github.com-personal:ujjwalks-ai/skill-doctor.git
ln -s "$(pwd)/skill-doctor" ~/.claude/skills/skill-doctor
```

## Usage

In any Claude Code session:

> Evaluate the skill at `~/.claude/skills/reconcile`

Or run the deterministic checks directly:

```bash
python3 scripts/audit.py ~/.claude/skills/reconcile --json
```

Audit an entire skills directory at once — cross-skill checks plus a per-skill
roll-up:

```bash
python3 scripts/audit.py ~/.claude/skills --repo
```

Repo mode catches what a single-folder audit structurally can't: duplicate
`name:` frontmatter (loader ambiguity), loose `<name>.md` files shadowing a
folder skill (stale copies), and skills whose trigger surfaces overlap so
heavily they may compete to fire.

### Run the real test — a paired eval

The static audit can't tell you the skill *helps*. `scripts/eval.py` runs the
paired eval automatically: it spawns fresh headless Claude contexts
(`claude -p`) as trigger judges and as with-skill vs baseline pass agents,
scores objective assertions, and reports **trigger rate and pass rate
separately**. It is dry by design (agents emit what they *would* run; the
harness disallows Bash/Edit/Write).

```bash
python3 scripts/eval.py examples/eval-reconcile.json --plan   # show the calls, cost nothing
python3 scripts/eval.py examples/eval-reconcile.json          # actually run it
```

A spec lists the skill path, realistic positive/negative trigger prompts, and
regex assertions for the pass check — see `examples/eval-reconcile.json`.

### Close the loop — propose and validate a fix

`scripts/iterate.py` is the v3 loop: it measures the gate, proposes a
**description** fix drawn from the trigger prompts the skill actually missed,
re-measures, and keeps the change only if positives improve and no negative
starts false-firing. It only touches the description and only re-measures trigger
(pass rate is body-driven). Nothing is written to the skill — the winning
description is staged to `<skill>/SKILL.md.proposed` for you to review and apply.

```bash
python3 scripts/iterate.py examples/eval-reconcile.json --max-iters 2
```

Edits are drafted *from observed failures*, never from imagination, and every
proposal is re-measured — the guard against the "model writes its own skill" trap.

## Development

Run the deterministic-check regression tests (stdlib only, no deps):

```bash
python3 -m unittest discover -s tests -v
```

Fixtures live in `tests/fixtures/` and `examples/`; secret cases are built in
temp dirs at runtime so no provider-format credential is ever committed.

## Roadmap

- **v1:** static audit + recommendations, with paired-eval scaffolding — done
- **v2:** run the paired eval harness — measure trigger rate and pass rate
  separately (`scripts/eval.py`) — done
- **v3:** the full loop — propose a description fix from observed trigger misses,
  re-measure, keep it only if it helps (`scripts/iterate.py`) — done

## Credit

The evaluation model is drawn from *The Art of Writing Skills* (three-tier
loading, the delta rule, description-as-gate, paired evaluation). skill-doctor
is an attempt to make that field guide runnable.

**Get the book → [The Art of Writing Skills](https://topmate.io/ujjwal_k_singh/2199504?utm_source=public_profile&utm_campaign=ujjwal_k_singh)**

## License

MIT — see [LICENSE](LICENSE).
