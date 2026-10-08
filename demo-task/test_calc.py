import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from calc import add, mul  # noqa: E402


class AddTests(unittest.TestCase):
    def test_add(self):
        self.assertEqual(add(2, 3), 5)

    def test_mul(self):
        self.assertEqual(mul(2, 4), 8)


if __name__ == "__main__":
    unittest.main()
