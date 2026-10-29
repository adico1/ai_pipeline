import unittest

from evaluations.requirements_review.coverage import CoverageReview, validate_coverage


class RequirementsCoverageTests(unittest.TestCase):
    def setUp(self):
        self.document = {"objective": "Rename tasks", "acceptance_criteria": ["Reject blank titles"]}
        self.requirements = [{"id": "titles", "task_quote": "Reject blank titles with exit 2"}]
        self.row = {
            "requirement_id": "titles", "coverage": "covered", "explanation": "Title validation",
            "citations": [{"field": "acceptance_criteria", "index": 0, "quote": "Reject blank titles"}],
        }

    def validate(self, rows):
        return validate_coverage(CoverageReview(items=rows), self.document, self.requirements)

    def test_real_quote_is_valid_but_does_not_prove_semantic_coverage(self):
        result = self.validate([self.row])
        self.assertTrue(result["evidence_valid"])
        # The missing exit code shows why human/semantic review is still needed.
        self.assertEqual(result["status"], "passed")

    def test_quote_from_original_task_cannot_stand_in_for_draft(self):
        self.row["citations"][0]["quote"] = self.requirements[0]["task_quote"]
        result = self.validate([self.row])
        self.assertFalse(result["evidence_valid"])
        self.assertEqual(result["status"], "blocked")

    def test_missing_duplicate_and_unknown_requirement_ids_fail(self):
        for rows in ([], [self.row, self.row], [{**self.row, "requirement_id": "invented"}]):
            with self.subTest(rows=rows):
                self.assertFalse(self.validate(rows)["evidence_valid"])

    def test_wrong_field_index_or_empty_evidence_fails(self):
        for citation in (
            {"field": "acceptance_criteria", "index": 1, "quote": "Reject blank titles"},
            {"field": "acceptance_criteria", "index": None, "quote": "Reject blank titles"},
            {"field": "objective", "index": 0, "quote": "Rename tasks"},
            {"field": "objective", "index": None, "quote": " "},
        ):
            with self.subTest(citation=citation):
                self.assertFalse(self.validate([{**self.row, "citations": [citation]}])["evidence_valid"])
        self.assertFalse(self.validate([{**self.row, "citations": []}])["evidence_valid"])

    def test_missing_or_partial_requirement_blocks_with_valid_evidence(self):
        for coverage in ("missing", "partial", "contradicted"):
            result = self.validate([{**self.row, "coverage": coverage, "citations": []}])
            self.assertTrue(result["evidence_valid"])
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["uncovered_requirements"], ["titles"])
