import re
import unittest

from app.domain.report_rendering import render_increment2_report


class ReportRenderingTests(unittest.TestCase):
    def test_rendering_order_and_format(self) -> None:
        files = [
            {"sort_index": 2, "name": "b.png", "file_id": "f2", "mime_type": "image/png"},
            {"sort_index": 1, "name": "a.jpg", "file_id": "f1", "mime_type": "image/jpeg"},
            {"sort_index": 1, "name": "a.jpg", "file_id": "f0", "mime_type": "image/jpeg"},
        ]
        output = render_increment2_report(
            job_id="job-123",
            folder_id="folder-abc",
            generated_at_local_iso="2025-01-01T12:00:00",
            files=files,
        )

        lines = output.splitlines()
        self.assertEqual(lines[0], "REPORT_VERSION: 1")
        self.assertEqual(lines[1], "JOB_ID: job-123")
        self.assertEqual(lines[2], "FOLDER_ID: folder-abc")
        self.assertEqual(lines[3], "GENERATED_AT: 2025-01-01T12:00:00")

        blocks = output.split("--- FILE START ---")
        self.assertEqual(len(blocks) - 1, 3)

        expected_order = [
            ("1", "a.jpg", "f0"),
            ("2", "a.jpg", "f1"),
            ("3", "b.png", "f2"),
        ]
        for block, expected in zip(blocks[1:], expected_order, strict=True):
            index, name, file_id = expected
            self.assertIn(f"INDEX: {index}", block)
            self.assertIn(f"FILE_NAME: {name}", block)
            self.assertIn(f"FILE_ID: {file_id}", block)
            self.assertIn("--- FILE END ---", block)
            self.assertIn("EXTRACTED_TEXT:\n<<<PENDING_EXTRACTION>>>", block)
            self.assertIn("EXTRACTED_FIELDS_JSON:\n<<<PENDING_EXTRACTION>>>", block)

        self.assertTrue(output.endswith("\n"))


if __name__ == "__main__":
    unittest.main()
