import unittest
from taskboard.domain import title, identifier

class DomainTests(unittest.TestCase):
    def test_blank_title(self):
        with self.assertRaises(ValueError): title(' ')
    def test_title_normalization(self):
        self.assertEqual(title(' hello '),'hello')
    def test_id_range(self):
        with self.assertRaises(ValueError): identifier(str(2**63))
