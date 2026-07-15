#!/usr/bin/env python3
"""
Offline tests for scripts/iterate.py — the deterministic logic only (miss
extraction, description validation, accept/reject rule). The claude -p calls
(measure_trigger / propose_description) are exercised by the smoke run, not here.
"""

import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
_spec = importlib.util.spec_from_file_location("skiterate", os.path.join(ROOT, "scripts", "iterate.py"))
it = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(it)


def measurement(pos, neg):
    """pos/neg: list of (prompt, fired, runs)."""
    per = {}
    for p, f, r in pos:
        per[("positive", p)] = {"fired": f, "runs": r}
    for p, f, r in neg:
        per[("negative", p)] = {"fired": f, "runs": r}
    return {"per": per,
            "pos_fired": sum(f for _, f, _ in pos), "pos_total": sum(r for _, _, r in pos),
            "neg_fired": sum(f for _, f, _ in neg), "neg_total": sum(r for _, _, r in neg)}


class TestFailures(unittest.TestCase):
    def test_extracts_missed_positives_and_false_fires(self):
        m = measurement(
            pos=[("build the model", 3, 3), ("configure entities", 0, 3)],
            neg=[("make a dashboard", 0, 3), ("create a KPI", 2, 3)])
        missed, false_fire = it.failures(m)
        self.assertEqual(missed, ["configure entities"])
        self.assertEqual(false_fire, ["create a KPI"])

    def test_converged_has_no_failures(self):
        m = measurement(pos=[("a", 3, 3)], neg=[("b", 0, 3)])
        missed, false_fire = it.failures(m)
        self.assertEqual(missed, [])
        self.assertEqual(false_fire, [])


class TestValidDescription(unittest.TestCase):
    def test_rejects_empty_angle_brackets_and_overlong(self):
        self.assertTrue(it.valid_description("A fine description."))
        self.assertFalse(it.valid_description(""))
        self.assertFalse(it.valid_description(None))
        self.assertFalse(it.valid_description("has <angle> brackets"))
        self.assertFalse(it.valid_description("x" * 1025))


class TestAcceptRule(unittest.TestCase):
    """The keep-only-if-it-helps rule, mirrored from run_iterate."""
    @staticmethod
    def improved(best, cand):
        return cand["pos_fired"] > best["pos_fired"] and cand["neg_fired"] <= best["neg_fired"]

    def test_keeps_strict_positive_gain_without_regression(self):
        best = measurement(pos=[("a", 2, 3)], neg=[("n", 0, 3)])
        cand = measurement(pos=[("a", 3, 3)], neg=[("n", 0, 3)])
        self.assertTrue(self.improved(best, cand))

    def test_rejects_positive_gain_that_regresses_a_negative(self):
        best = measurement(pos=[("a", 2, 3)], neg=[("n", 0, 3)])
        cand = measurement(pos=[("a", 3, 3)], neg=[("n", 1, 3)])
        self.assertFalse(self.improved(best, cand))

    def test_rejects_no_positive_gain(self):
        best = measurement(pos=[("a", 3, 3)], neg=[("n", 0, 3)])
        cand = measurement(pos=[("a", 3, 3)], neg=[("n", 0, 3)])
        self.assertFalse(self.improved(best, cand))


if __name__ == "__main__":
    unittest.main(verbosity=2)
