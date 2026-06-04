"""
Unit tests for UEProcessManager — the open_editor/close_editor backbone.

Pure-logic coverage with temp dirs and fakes; does NOT require a real Unreal
Editor. Tests focus on:
  - resolve_engine_root: EngineAssociation parsing (in-tree, GUID, version, path)
  - UEProject.sln_stale / binaries_stale: rebuild trigger heuristics
  - UEProject.scan_log_status: ready/crash/pending detection
  - UEProject construction: path derivation

Run:  python Tests/test_ue_process_manager.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


# ─────────────────────────────────────────────────────────────────────────────
# Load UEProcessManager directly from the plugin source tree.
# Content/Python/mcp_server isn't on the default sys.path, so we load it via
# importlib rather than reorganizing the test runner.
# ─────────────────────────────────────────────────────────────────────────────

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
_UPM_PATH = _PLUGIN_ROOT / "Content" / "Python" / "mcp_server" / "UEProcessManager.py"

_spec = importlib.util.spec_from_file_location("UEProcessManager", _UPM_PATH)
P = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(P)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

def _make_engine(root: Path) -> Path:
    """Create a fake engine tree with Build.version + batch files + editor exe."""
    bf = root / "Engine" / "Build" / "BatchFiles"
    bf.mkdir(parents=True, exist_ok=True)
    (root / "Engine" / "Build" / "Build.version").write_text("{}", encoding="utf-8")
    (bf / "GenerateProjectFiles.bat").write_text("@echo off", encoding="utf-8")
    (bf / "Build.bat").write_text("@echo off", encoding="utf-8")
    bin_dir = root / "Engine" / "Binaries" / "Win64"
    bin_dir.mkdir(parents=True, exist_ok=True)
    (bin_dir / "UnrealEditor.exe").write_text("", encoding="utf-8")
    return root


def _make_project(root: Path, assoc: str, name: str = "MyGame") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    up = root / f"{name}.uproject"
    up.write_text(
        json.dumps({"FileVersion": 3, "EngineAssociation": assoc}),
        encoding="utf-8"
    )
    return up


# ─────────────────────────────────────────────────────────────────────────────
class TestEngineResolution(unittest.TestCase):
    def test_case_A_empty_intree(self):
        with TemporaryDirectory() as d:
            d = Path(d)
            engine = _make_engine(d / "UE")
            # in-tree layout: <engine>/MyGame/MyGame.uproject (parent.parent == engine)
            up = _make_project(engine / "MyGame", "")
            got = P.resolve_engine_root("", up)
            self.assertEqual(got.resolve(), engine.resolve())

    def test_case_A_empty_no_engine_raises(self):
        with TemporaryDirectory() as d:
            up = _make_project(Path(d) / "Proj", "")
            with self.assertRaises(RuntimeError):
                P.resolve_engine_root("", up)

    def test_case_D_absolute_path(self):
        with TemporaryDirectory() as d:
            d = Path(d)
            engine = _make_engine(d / "UnrealEngine")
            up = _make_project(d / "Proj", str(engine))
            got = P.resolve_engine_root(str(engine), up)
            self.assertEqual(got.resolve(), engine.resolve())

    def test_case_D_forward_slashes(self):
        with TemporaryDirectory() as d:
            d = Path(d)
            engine = _make_engine(d / "UnrealEngine")
            up = _make_project(d / "Proj", "")
            assoc = str(engine).replace("\\", "/")
            got = P.resolve_engine_root(assoc, up)
            self.assertEqual(got.resolve(), engine.resolve())

    def test_case_D_path_no_engine_raises(self):
        with TemporaryDirectory() as d:
            d = Path(d)
            up = _make_project(d / "Proj", "")
            with self.assertRaises(RuntimeError):
                P.resolve_engine_root(str(d / "NoEngineHere"), up)

    def test_case_C_version_not_found_raises(self):
        with TemporaryDirectory() as d:
            up = _make_project(Path(d) / "Proj", "")
            # version "0.0" should never be in the registry
            with self.assertRaises(RuntimeError):
                P.resolve_engine_root("0.0", up)


# ─────────────────────────────────────────────────────────────────────────────
class TestStaleDetection(unittest.TestCase):
    def _proj(self, d: Path, name="MyGame"):
        engine = _make_engine(d / "UnrealEngine")
        up = _make_project(d / "Proj", str(engine), name)
        return P.UEProject(up, engine_root=engine)

    def test_sln_missing_is_stale(self):
        with TemporaryDirectory() as d:
            proj = self._proj(Path(d))
            self.assertTrue(proj.sln_stale())

    def test_sln_newer_than_uproject_not_stale(self):
        with TemporaryDirectory() as d:
            proj = self._proj(Path(d))
            sln = proj.project_dir / "MyGame.sln"
            sln.write_text("", encoding="utf-8")
            # make sln newer
            future = time.time() + 100
            os.utime(sln, (future, future))
            self.assertFalse(proj.sln_stale())

    def test_uproject_newer_than_sln_is_stale(self):
        with TemporaryDirectory() as d:
            proj = self._proj(Path(d))
            sln = proj.project_dir / "MyGame.sln"
            sln.write_text("", encoding="utf-8")
            past = time.time() - 1000
            os.utime(sln, (past, past))
            self.assertTrue(proj.sln_stale())

    def test_binaries_missing_is_stale(self):
        with TemporaryDirectory() as d:
            proj = self._proj(Path(d))
            (proj.project_dir / "Source").mkdir(exist_ok=True)
            self.assertTrue(proj.binaries_stale())

    def test_binaries_newer_than_source_not_stale(self):
        with TemporaryDirectory() as d:
            proj = self._proj(Path(d))
            src = proj.project_dir / "Source"
            src.mkdir(exist_ok=True)
            (src / "Foo.cpp").write_text("// code", encoding="utf-8")
            bin_dir = proj.project_dir / "Binaries" / "Win64"
            bin_dir.mkdir(parents=True, exist_ok=True)
            dll = bin_dir / "UnrealEditor-MyGame.dll"
            dll.write_text("", encoding="utf-8")
            future = time.time() + 100
            os.utime(dll, (future, future))
            self.assertFalse(proj.binaries_stale())

    def test_source_newer_than_binaries_is_stale(self):
        with TemporaryDirectory() as d:
            proj = self._proj(Path(d))
            src = proj.project_dir / "Source"
            src.mkdir(exist_ok=True)
            cpp = src / "Foo.cpp"
            cpp.write_text("// code", encoding="utf-8")
            bin_dir = proj.project_dir / "Binaries" / "Win64"
            bin_dir.mkdir(parents=True, exist_ok=True)
            dll = bin_dir / "UnrealEditor-MyGame.dll"
            dll.write_text("", encoding="utf-8")
            past = time.time() - 1000
            os.utime(dll, (past, past))
            self.assertTrue(proj.binaries_stale())


# ─────────────────────────────────────────────────────────────────────────────
class TestLogScanning(unittest.TestCase):
    def test_ready_detected(self):
        lines = ["LogX: foo", "LogInit: Display: Engine is initialized. Leaving FEngineLoop"]
        status, _ = P.UEProject.scan_log_status(lines)
        self.assertEqual(status, "ready")

    def test_crash_detected(self):
        lines = ["LogX: foo", "Fatal error: [File:...] crash here"]
        status, _ = P.UEProject.scan_log_status(lines)
        self.assertEqual(status, "crash")

    def test_pending(self):
        lines = ["LogX: loading", "LogY: still going"]
        status, _ = P.UEProject.scan_log_status(lines)
        self.assertEqual(status, "pending")

    def test_ready_takes_priority_over_earlier_crash(self):
        # ready appears AFTER a stale crash → ready wins
        lines = ["Assertion failed: old", "Engine is initialized"]
        status, _ = P.UEProject.scan_log_status(lines)
        self.assertEqual(status, "ready")

    def test_crash_after_ready_is_crash(self):
        # crash appears AFTER ready → crash wins (regression of earlier session)
        lines = ["Engine is initialized", "Fatal error: late crash"]
        status, _ = P.UEProject.scan_log_status(lines)
        self.assertEqual(status, "crash")


# ─────────────────────────────────────────────────────────────────────────────
class TestUEProjectInit(unittest.TestCase):
    def test_missing_uproject_raises(self):
        with self.assertRaises(FileNotFoundError):
            P.UEProject("Z:/nonexistent/Foo.uproject", engine_root=Path("Z:/eng"))

    def test_paths_constructed(self):
        with TemporaryDirectory() as d:
            d = Path(d)
            engine = _make_engine(d / "UnrealEngine")
            up = _make_project(d / "Proj", str(engine), "MyGame")
            proj = P.UEProject(up, engine_root=engine)
            self.assertEqual(proj.project_name, "MyGame")
            self.assertTrue(str(proj.gpf_bat).endswith("GenerateProjectFiles.bat"))
            self.assertTrue(str(proj.editor_log).endswith("MyGame.log"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
