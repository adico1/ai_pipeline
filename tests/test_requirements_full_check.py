import unittest

from evaluations.requirements_review.full_check import control_document, load_checklist


class FullChecklistTests(unittest.TestCase):
    def test_every_source_group_is_represented_with_unique_items(self):
        checklist, task = load_checklist()
        self.assertEqual(len(checklist), 55)
        self.assertEqual(len({item['group'] for item in checklist}), 9)
        for item in checklist:
            self.assertIn(item['task_quote'], task)

    def test_control_pair_changes_only_selected_rule(self):
        checklist, _ = load_checklist()
        for item in checklist:
            present = control_document(item, True)
            omitted = control_document(item, False)
            self.assertEqual(present['acceptance_criteria'], [item['requirement']])
            self.assertNotIn(item['requirement'], str(omitted))
            present.pop('acceptance_criteria')
            omitted.pop('acceptance_criteria')
            self.assertEqual(present, omitted)
