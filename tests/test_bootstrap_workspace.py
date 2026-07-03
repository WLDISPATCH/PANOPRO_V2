from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path
from uuid import uuid4


TEST_TMP_ROOT = Path(".test_tmp")
SCRIPT_PATH = Path("scripts/bootstrap_workspace.ps1").resolve()


class BootstrapWorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TMP_ROOT.mkdir(exist_ok=True)
        self.base_dir = (TEST_TMP_ROOT / f"bootstrap_{uuid4().hex}").resolve()
        self.source_root = self.base_dir / "source"
        self.destination_root = self.base_dir / "targets"
        self.source_root.mkdir(parents=True, exist_ok=True)
        self.destination_root.mkdir(parents=True, exist_ok=True)
        self._build_fake_source_tree()

    def tearDown(self) -> None:
        shutil.rmtree(self.base_dir, ignore_errors=True)

    def _write(self, relative_path: str, content: str | bytes) -> None:
        target = self.source_root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")

    def _build_fake_source_tree(self) -> None:
        self._write("pano_namer/__init__.py", '__version__ = "1.1.0"\n')
        self._write("pano_namer/main.py", 'APP = "ok"\n')
        self._write("scripts/build_release.ps1", 'Write-Host "build"\n')
        self._write("installer/PANO-PRO.iss", '#define AppVersion "1.1.0"\n')
        self._write("tests/test_sample.py", "def test_placeholder():\n    assert True\n")
        self._write("README.md", "- `dist\\PANO-PRO-v1.1.0-windows.zip`\n- `dist\\installer\\PANO-PRO-Setup-1.1.0.exe`\n-Version \"2.0.0-dev\"\n")
        self._write("requirements.txt", "fastapi\n")
        self._write("PANO-PRO.spec", "spec\n")
        self._write(".gitignore", "dist/\n")
        self._write("Start Pano Namer.bat", "echo start\n")
        self._write("inlinegroupinc_logo.ico", b"ico")
        self._write(".pano_namer_data/pano_namer.db", b"db")
        self._write("build/artifact.txt", "ignore\n")
        self._write("dist/package.txt", "ignore\n")
        self._write(".test_tmp/temp.txt", "ignore\n")
        self._write("pano_namer/__pycache__/cached.pyc", b"cache")
        self._write("tests/helper.pyc", b"cache")

    def test_bootstrap_creates_clean_versioned_workspace(self) -> None:
        target_name = "PANO PRO v2"
        command = [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT_PATH),
            "-SourceRoot",
            str(self.source_root),
            "-DestinationRoot",
            str(self.destination_root),
            "-TargetName",
            target_name,
            "-Version",
            "2.0.0-dev",
            "-IncludeData",
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        self.assertIn("Created workspace:", result.stdout)

        target_root = self.destination_root / target_name
        self.assertTrue((target_root / "pano_namer").is_dir())
        self.assertTrue((target_root / "tests").is_dir())
        self.assertTrue((target_root / "scripts").is_dir())
        self.assertTrue((target_root / "installer").is_dir())
        self.assertTrue((target_root / ".pano_namer_data").is_dir())
        self.assertTrue((target_root / "README.md").is_file())
        self.assertTrue((target_root / "requirements.txt").is_file())
        self.assertTrue((target_root / "PANO-PRO.spec").is_file())

        self.assertFalse((target_root / "build").exists())
        self.assertFalse((target_root / "dist").exists())
        self.assertFalse((target_root / ".test_tmp").exists())
        self.assertFalse((target_root / "pano_namer/__pycache__").exists())
        self.assertFalse((target_root / "tests/helper.pyc").exists())

        init_content = (target_root / "pano_namer/__init__.py").read_text(encoding="utf-8")
        self.assertIn('__version__ = "2.0.0-dev"', init_content)
        installer_content = (target_root / "installer/PANO-PRO.iss").read_text(encoding="utf-8")
        self.assertIn('#define AppVersion "2.0.0-dev"', installer_content)
        readme_content = (target_root / "README.md").read_text(encoding="utf-8")
        self.assertIn("PANO-PRO-v2.0.0-dev-windows.zip", readme_content)
        self.assertIn("PANO-PRO-Setup-2.0.0-dev.exe", readme_content)
        self.assertTrue((target_root / ".pano_namer_data/pano_namer.db").exists())


if __name__ == "__main__":
    unittest.main()
