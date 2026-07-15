#!/usr/bin/env python3
"""
Regression tests for scripts/audit.py.

Run from the repo root:
    python3 -m unittest discover -s tests -v
or directly:
    python3 tests/test_audit.py

Committed fixtures live in tests/fixtures/ and examples/. Secret cases are built
in temp dirs at runtime so no provider-format credential is ever committed.
"""

import importlib.util
import os
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

_spec = importlib.util.spec_from_file_location("audit", os.path.join(ROOT, "scripts", "audit.py"))
audit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(audit)


def run(path):
    return audit.check_skill(path)  # -> (summary, findings)


def has(findings, check, severity=None):
    return any(f["check"] == check and (severity is None or f["severity"] == severity)
               for f in findings)


def write_skill(parent, name, body,
                desc="A fixture skill for tests. Use this whenever the tests need it."):
    d = os.path.join(parent, name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "SKILL.md"), "w") as fh:
        fh.write(f"---\nname: {name}\ndescription: {desc}\n---\n\n# {name}\n\n{body}\n")
    return d


class TestCommittedFixtures(unittest.TestCase):
    def test_sample_skill_expected_findings(self):
        summary, f = run(os.path.join(ROOT, "examples", "sample-skill"))
        self.assertEqual(summary["errors"], 0)
        self.assertTrue(has(f, "description", "warn"), "short description should warn")
        self.assertTrue(has(f, "routing", "warn"), "weak 'see X.md' pointer should warn")
        self.assertTrue(has(f, "references", "warn"), "reference chain should warn")
        self.assertFalse(has(f, "secret"), "sample-skill has no secrets")
        self.assertFalse(has(f, "embedded-code", "warn"), "sample-skill has no heavy code")

    def test_clean_fixture_is_spotless(self):
        summary, _ = run(os.path.join(HERE, "fixtures", "clean"))
        self.assertEqual(summary["errors"], 0)
        self.assertEqual(summary["warnings"], 0)

    def test_embedded_pipeline_warns(self):
        _, f = run(os.path.join(HERE, "fixtures", "embedded-pipeline"))
        self.assertTrue(has(f, "embedded-code", "warn"))


class TestSecretScanner(unittest.TestCase):
    def test_hardcoded_webhook_errors_and_is_redacted(self):
        token = "T01ABCD2EFG/B01HIJK3LMN/abcdefGHIJKLmnop0123456789"
        with tempfile.TemporaryDirectory() as tmp:
            d = write_skill(tmp, "leaky",
                            "Post it:\n\n```bash\ncurl -d x https://hooks.slack.com/services/"
                            + token + "\n```")
            _, f = run(d)
        self.assertTrue(has(f, "secret", "error"))
        secrets = [x for x in f if x["check"] == "secret"]
        # the raw token must never be echoed; it must be redacted
        for x in secrets:
            self.assertNotIn("abcdefGHIJKLmnop", x.get("detail", ""))
        self.assertTrue(any("«REDACTED»" in x.get("detail", "") for x in secrets))

    def test_generic_credential_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = write_skill(tmp, "generic", "Config:\n\n    password = s3cr3tvalue1234567890")
            _, f = run(d)
        self.assertTrue(has(f, "secret", "warn"))

    def test_placeholder_and_envvar_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = write_skill(tmp, "safe",
                            "Set `token = $MY_TOKEN` and use hooks.slack.com/services/… during setup.")
            _, f = run(d)
        self.assertFalse(has(f, "secret"))


class TestRepoMode(unittest.TestCase):
    REPO = os.path.join(HERE, "fixtures", "repo")

    def test_discovers_folder_and_loose_skills(self):
        found = sorted((s["name"], s["kind"]) for s in audit.discover_skills(self.REPO))
        self.assertIn(("alpha", "folder"), found)
        self.assertIn(("alpha", "loose"), found)
        self.assertIn(("beta", "folder"), found)

    def test_duplicate_name_is_error(self):
        _, payload = audit.audit_repo(self.REPO)
        self.assertTrue(any(f["check"] == "duplicate-name" and f["severity"] == "error"
                            for f in payload["cross_findings"]))

    def test_shadow_copy_warns(self):
        _, payload = audit.audit_repo(self.REPO)
        self.assertTrue(has(payload["cross_findings"], "shadow-copy", "warn"))

    def test_trigger_overlap_flagged(self):
        _, payload = audit.audit_repo(self.REPO)
        self.assertTrue(has(payload["cross_findings"], "trigger-overlap", "info"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
