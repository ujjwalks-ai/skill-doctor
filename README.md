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
  `key = value` credentials (warn). Matched values are redacted in the report.

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

## Development

Run the deterministic-check regression tests (stdlib only, no deps):

```bash
python3 -m unittest discover -s tests -v
```

Fixtures live in `tests/fixtures/` and `examples/`; secret cases are built in
temp dirs at runtime so no provider-format credential is ever committed.

## Roadmap

- **v1 (now):** static audit + recommendations, with paired-eval scaffolding
- **v2:** run the paired eval harness — measure trigger rate and pass rate
- **v3:** the full loop — propose edits, re-measure against a baseline snapshot,
  iterate

## Credit

The evaluation model is drawn from *The Art of Writing Skills* (three-tier
loading, the delta rule, description-as-gate, paired evaluation). skill-doctor
is an attempt to make that field guide runnable.

**Get the book → [The Art of Writing Skills](https://topmate.io/ujjwal_k_singh/2199504?utm_source=public_profile&utm_campaign=ujjwal_k_singh)**

## License

MIT — see [LICENSE](LICENSE).
