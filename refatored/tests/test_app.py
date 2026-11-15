import io
import sys
import unittest
from unittest.mock import patch

from refatored.app import configure_output_encoding, print_banner


class TestAppOutput(unittest.TestCase):
    def test_banner_is_printed_when_stdout_uses_cp1252(self):
        stdout_buffer = io.BytesIO()
        stderr_buffer = io.BytesIO()
        stdout = io.TextIOWrapper(stdout_buffer, encoding="cp1252")
        stderr = io.TextIOWrapper(stderr_buffer, encoding="cp1252")

        with patch.object(sys, "stdout", stdout), patch.object(sys, "stderr", stderr):
            configure_output_encoding()
            print_banner()
            stdout.flush()

        banner = stdout_buffer.getvalue().decode("utf-8")
        self.assertIn("AURORA ASSISTANT 2.0", banner)
        self.assertIn("╔", banner)


if __name__ == "__main__":
    unittest.main()
