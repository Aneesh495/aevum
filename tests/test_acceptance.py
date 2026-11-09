import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from aevum.acceptance import FULL_STEPS, _full_pass, _gates, _release_review


class AcceptanceTests(unittest.TestCase):
    def test_full_verdict_requires_every_gate_and_a_full_profile(self):
        gates = _gates("full", set(FULL_STEPS), (129, 121))
        self.assertEqual(gates["G06"]["status"], "failed")
        gates["G13"] = gates["G15"] = {"status": "passed"}
        self.assertFalse(_full_pass("full", gates))

        gates["G06"] = {"status": "passed"}
        self.assertTrue(_full_pass("full", gates))
        self.assertFalse(_full_pass("diagnostic", gates))
        del gates["G13"]
        self.assertFalse(_full_pass("full", gates))

    def test_release_review_requires_trusted_digest_and_matching_campaign(self):
        with TemporaryDirectory() as temporary:
            folder = Path(temporary)
            candidate = folder / "candidate"
            candidate.mkdir()
            manifest = b"{}\n"
            (candidate / "MANIFEST.json").write_bytes(manifest)
            review = {
                "source_commit": "source",
                "manifest_sha256": hashlib.sha256(manifest).hexdigest(),
                "reviewer": "Test reviewer",
                "report": "Test report",
                "checks": dict.fromkeys(
                    ("capability_audit", "private_requirements", "clean_checkout_demo", "hosted_publication"),
                    "passed",
                ),
            }
            external = folder / "review.json"
            data = json.dumps(review).encode()
            external.write_bytes(data)
            trusted = hashlib.sha256(data).hexdigest()

            self.assertEqual(_release_review(external, trusted, candidate, "source")["status"], "passed")
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                _release_review(external, "0" * 64, candidate, "source")
            with self.assertRaisesRegex(ValueError, "different source or campaign"):
                _release_review(external, trusted, candidate, "different")
            internal = candidate / "review.json"
            internal.write_bytes(data)
            with self.assertRaisesRegex(ValueError, "external"):
                _release_review(internal, trusted, candidate, "source")


if __name__ == "__main__":
    unittest.main()
