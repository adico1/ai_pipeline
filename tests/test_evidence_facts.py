import unittest

from ai_pipeline.evidence_facts import describe_check


class EvidenceFactsTests(unittest.TestCase):
    def describe(self, expected, actual):
        return describe_check({'stage': 'verify', 'status': 'failed',
                               'detail': {'case': 'example', 'expected': expected, 'actual': actual}})

    def test_types_missing_extra_keys_and_json_pointer_escaping(self):
        result = self.describe({'a/b': True, 'missing': 1}, {'a/b': 1, 'extra': 2})
        self.assertIn('/a~1b: expected true; observed 1', result)
        self.assertIn('/missing: missing', result)
        self.assertIn('/extra: unexpected', result)

    def test_unstructured_expectations_and_equal_values_do_not_invent_causes(self):
        self.assertIn('expected "exit 2"; observed', self.describe('exit 2', {'exit_code': 0}))
        self.assertIn('values match', self.describe({'id': 1}, {'id': 1}))

    def test_list_length_difference_is_reported_without_identity_assumptions(self):
        self.assertIn('expected [1]; observed [1, 2]', self.describe([1], [1, 2]))
