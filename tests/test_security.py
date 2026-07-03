from __future__ import annotations

import unittest

from pano_namer.security import hash_password, verify_password


class PasswordHashingTests(unittest.TestCase):
    def test_hash_password_does_not_return_plain_password(self) -> None:
        password = "correct-horse-battery-staple"

        password_hash = hash_password(password)

        self.assertNotEqual(password_hash, password)
        self.assertNotIn(password, password_hash)

    def test_verify_password_accepts_matching_password_only(self) -> None:
        password_hash = hash_password("secret-password")

        self.assertTrue(verify_password("secret-password", password_hash))
        self.assertFalse(verify_password("wrong-password", password_hash))
        self.assertFalse(verify_password("secret-password", ""))


if __name__ == "__main__":
    unittest.main()
