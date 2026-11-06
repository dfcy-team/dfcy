import unittest
from tk_two_shop_nightly import command, digest, SHOPS


class RunnerTests(unittest.TestCase):
    def test_line_endings_only(self):
        self.assertEqual(digest(b'a\r\nb\r\n'), digest(b'a\nb\n'))
        self.assertNotEqual(digest(b'a\nb\n'), digest(b'a\nc\n'))

    def test_scope(self):
        self.assertEqual(SHOPS, (15, 67))
        for store in SHOPS:
            cmd = command(store)
            self.assertEqual(cmd[cmd.index('--days') + 1], '1')
            self.assertNotIn('--refresh', cmd)
            self.assertNotIn('--all-authorized', cmd)
        with self.assertRaises(ValueError):
            command(23)


if __name__ == '__main__':
    unittest.main()
