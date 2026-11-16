from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class PackagingTests(unittest.TestCase):
    def test_document_dependencies_removed(self):
        requirements = (ROOT / 'requirements.txt').read_text().lower()
        for removed in ('python-docx', 'fpdf2', 'arabic-reshaper', 'python-bidi'):
            self.assertNotIn(removed, requirements)

    def test_runtime_dependencies_pinned(self):
        lines = (ROOT / 'requirements.txt').read_text().splitlines()
        for line in lines:
            if line.strip() and not line.startswith('#'):
                self.assertIn('==', line)

    def test_sensitive_data_ignored(self):
        ignore = (ROOT / '.gitignore').read_text()
        for pattern in ('.env', '*.session', '*.db', 'private-cache/', 'work/', '.venv/'):
            self.assertIn(pattern, ignore)
