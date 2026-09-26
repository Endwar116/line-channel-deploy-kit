# -*- coding: utf-8 -*-
"""install.py 乾淨安裝煙霧測試：新工具都要出貨，出貨後的測試要能在安裝樹裡跑綠。"""
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest

KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
NEW_TOOLS = ("health_check.py", "task_runner.py", "read_doc.py", "video_digest.py")


def run_install(home, extra_env=None):
    env = dict(os.environ, HOME=home)
    env.update(extra_env or {})
    return subprocess.run([sys.executable, os.path.join(KIT, "install.py"),
                           "--owner", "測試主人", "--agent-name", "測試值台", "--slug", "kittest",
                           "--port", "8799", "--skip-launchd", "--yes"],
                          capture_output=True, text=True, env=env, timeout=300)


class CleanInstall(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = tempfile.mkdtemp()
        cls.r = run_install(cls.home)
        cls.base = os.path.join(cls.home, ".kittest")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.home)

    def test_installer_succeeds(self):
        self.assertEqual(self.r.returncode, 0, self.r.stdout[-800:] + self.r.stderr[-800:])

    def test_kit_only_test_is_not_shipped(self):
        self.assertFalse(os.path.exists(os.path.join(self.base, "tools", "tests", "test_install.py")))

    def test_new_tools_are_shipped(self):
        for f in NEW_TOOLS:
            self.assertTrue(os.path.exists(os.path.join(self.base, "tools", f)), f)
        self.assertTrue(os.path.exists(os.path.join(self.base, "tools", "bin", "ocr.swift")))

    def test_system_brief_is_created(self):
        self.assertTrue(os.path.exists(os.path.join(self.base, "config", "system_brief.md")))

    def test_shipped_tests_pass_in_install_tree(self):
        r = subprocess.run(["/usr/bin/python3", "-m", "unittest", "discover", "-s", "tests"],
                           cwd=os.path.join(self.base, "tools"), capture_output=True, text=True,
                           env=dict(os.environ, HOME=self.home), timeout=600)
        self.assertIn("OK", r.stderr[-300:], r.stderr[-1500:])


class PlistTemplates(unittest.TestCase):
    def test_templates_render_to_valid_plists(self):
        sys.path.insert(0, KIT)
        import install
        for name, interval in (("healthcheck", 3600), ("taskrunner", 900)):
            p = os.path.join(KIT, "templates", "launchd", f"com.SLUG.{name}.plist.tmpl")
            xml = install.render(p, {"SLUG": "acme", "HOME": "/Users/a", "BASE": "/Users/a/.acme",
                                     "PYTHON": "/usr/bin/python3", "PORT": "8700"})
            d = plistlib.loads(xml.encode())
            self.assertEqual(d["Label"], f"com.acme.{name}")
            self.assertEqual(d["StartInterval"], interval)
            self.assertEqual(d["StandardOutPath"], f"/Users/a/Library/Logs/acme-{name}.log")


class NoSwiftc(unittest.TestCase):
    def test_install_without_swiftc_still_succeeds(self):
        home = tempfile.mkdtemp()
        try:
            r = run_install(home, {"KIT_NO_SWIFTC": "1"})
            self.assertEqual(r.returncode, 0, r.stdout[-800:])
            self.assertIn("OCR", r.stdout)
            self.assertIn("PENDING", r.stdout)
        finally:
            shutil.rmtree(home)


if __name__ == "__main__":
    unittest.main()
