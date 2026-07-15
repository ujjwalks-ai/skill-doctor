#!/usr/bin/env python3
"""
Offline regression tests for scripts/eval.py — the deterministic helpers only
(spec loading, prompt construction, assertion scoring, choice parsing). The
`claude -p` calls are not exercised here; those are covered by `--plan` and a
manual smoke run.

Run: python3 -m unittest discover -s tests -v
"""

import importlib.util
import json
import os
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

_spec = importlib.util.spec_from_file_location("skdeval", os.path.join(ROOT, "scripts", "eval.py"))
ev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ev)


def make_skill(parent):
    d = os.path.join(parent, "demo")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "SKILL.md"), "w") as fh:
        fh.write("---\nname: demo\ndescription: A demo skill. Use when you demo.\n---\n\n"
                 "# Demo\n\nRun `scripts/demo.py go` to do the thing.\n")
    return d


class TestSpecLoading(unittest.TestCase):
    def test_defaults_and_skill_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = make_skill(tmp)
            spec_path = os.path.join(tmp, "spec.json")
            with open(spec_path, "w") as fh:
                json.dump({"skill_path": skill,
                           "trigger": {"positive": ["do the demo"]}}, fh)
            spec = ev.load_spec(spec_path)
        self.assertEqual(spec["name"], "demo")
        self.assertIn("demo skill", spec["description"])
        self.assertIn("scripts/demo.py", spec["_body"])
        self.assertEqual(spec["runs"], 3)                 # default
        self.assertEqual(spec["model"], ev.DEFAULT_MODEL)  # default
        self.assertEqual(spec["trigger"]["negative"], [])  # filled


class TestPrompts(unittest.TestCase):
    def _spec(self):
        return {"name": "demo", "description": "A demo skill.", "decoys": [
            {"name": "other", "description": "Something else."}], "_body": "BODY-MARKER"}

    def test_trigger_prompt_lists_skill_and_decoy(self):
        p = ev.build_trigger_prompt(self._spec(), "please demo it")
        self.assertIn("demo — A demo skill.", p)
        self.assertIn("other — Something else.", p)
        self.assertIn("please demo it", p)
        self.assertIn('"skill"', p)  # asks for JSON choice

    def test_pass_prompt_with_skill_includes_body_and_is_dry(self):
        p = ev.build_pass_prompt(self._spec(), "do it", True)
        self.assertIn("BODY-MARKER", p)
        self.assertIn("DO NOT execute", p)

    def test_pass_prompt_baseline_excludes_body(self):
        p = ev.build_pass_prompt(self._spec(), "do it", False)
        self.assertNotIn("BODY-MARKER", p)
        self.assertIn("no special project skill", p)


class TestScoring(unittest.TestCase):
    def test_score_assertions(self):
        text = "I would run recon.py trigger --limit 10 then recon.py failures."
        asserts = [{"desc": "trigger", "pattern": r"recon\.py trigger.*--limit\s*10"},
                   {"desc": "status", "pattern": r"recon\.py status"}]
        scored = ev.score_assertions(text, asserts)
        self.assertTrue(scored[0]["ok"])
        self.assertFalse(scored[1]["ok"])

    def test_parse_skill_choice(self):
        self.assertEqual(ev.parse_skill_choice('{"skill": "reconcile"}'), "reconcile")
        self.assertEqual(ev.parse_skill_choice('{"skill":"NONE"}'), "NONE")
        self.assertEqual(ev.parse_skill_choice("reconcile"), "reconcile")


if __name__ == "__main__":
    unittest.main(verbosity=2)
