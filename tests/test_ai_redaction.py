import unittest


class AIRedactionTests(unittest.TestCase):
    def test_common_unnecessary_pii_is_removed_without_changing_year_range(self):
        from app.ai.redaction import sanitize_text

        source = (
            "Nguyen Van A worked 2020-2024. Email a@example.com; phone +84 912 345 678.\n"
            "Địa chỉ: 12 Example Street"
        )
        sanitized = sanitize_text(source, known_names=("Nguyen Van A",))

        self.assertNotIn("Nguyen Van A", sanitized)
        self.assertNotIn("a@example.com", sanitized)
        self.assertNotIn("912 345 678", sanitized)
        self.assertNotIn("12 Example Street", sanitized)
        self.assertIn("2020-2024", sanitized)


if __name__ == "__main__":
    unittest.main()
