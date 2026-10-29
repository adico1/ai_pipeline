import json
from pathlib import Path
import unittest

from evaluations.requirements_review.atomic import atomic_cases


ROOT = Path(__file__).resolve().parents[1]


class AtomicRequirementsTests(unittest.TestCase):
    def setUp(self):
        directory = ROOT / "evaluations/requirements_review"
        self.complete = json.loads((directory / "cases.json").read_text())[0]["document"]
        self.checklist = json.loads((directory / "atomic-checklist.json").read_text())
        self.task = (ROOT / "projects/taskboard-rename-task.txt").read_text()

    def test_mutations_change_only_one_named_detail_and_leave_baseline_intact(self):
        before = json.dumps(self.complete)
        cases = atomic_cases(self.complete, self.checklist, self.task)
        self.assertEqual(len(cases), 6)
        for check, positive, negative in zip(self.checklist, cases[::2], cases[1::2]):
            self.assertEqual(positive["document"], self.complete)
            changed = negative["document"]
            for field, value in self.complete.items():
                if field != "acceptance_criteria":
                    self.assertEqual(changed[field], value)
            for index, value in enumerate(self.complete["acceptance_criteria"]):
                expected = value.replace(check["remove_text"], check["replacement"], 1) if index == check["criterion_index"] else value
                self.assertEqual(changed["acceptance_criteria"][index], expected)
            self.assertEqual(len(negative["requirements"]), 1)
            self.assertEqual(set(negative["requirements"][0]), {"id", "requirement", "task_quote"})
        self.assertEqual(json.dumps(self.complete), before)

    def test_untraceable_and_unapplied_mutations_are_rejected(self):
        for changes in ({"task_quote": "invented requirement"}, {"remove_text": "not in draft"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                atomic_cases(self.complete, [{**self.checklist[0], **changes}], self.task)
        with self.assertRaises(ValueError):
            atomic_cases(self.complete, [self.checklist[0], self.checklist[0]], self.task)
