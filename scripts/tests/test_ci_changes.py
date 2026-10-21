import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("ci_changes", Path(__file__).parents[1] / "ci_changes.py")
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)


class CheckSelection(unittest.TestCase):
    def test_frontend_pr_does_not_build_arm64_or_start_postgres(self):
        selected = ci.select_checks(["apps/web/src/App.tsx"], "pull_request")
        self.assertEqual(selected, {"web": True, "backend": False, "package": False, "scripts": False, "embedder": False})

    def test_backend_pr_runs_database_and_packaging_checks(self):
        selected = ci.select_checks(["backend/src/job_hunter/config.py"], "pull_request")
        self.assertTrue(selected["backend"] and selected["package"])

    def test_embedder_only_pr_runs_only_the_embedder_checks(self):
        selected = ci.select_checks(["services/embedder/src/embedder_service/config.py"], "pull_request")
        self.assertEqual(selected, {"web": False, "backend": False, "package": False, "scripts": False, "embedder": True})

    def test_a_backend_or_web_pr_does_not_run_the_embedder_checks(self):
        self.assertFalse(ci.select_checks(["backend/src/job_hunter/config.py"], "pull_request")["embedder"])
        self.assertFalse(ci.select_checks(["apps/web/src/App.tsx"], "pull_request")["embedder"])

    def test_files_that_decide_whether_the_embed_worker_image_builds_run_the_embedder_checks(self):
        for path in ("backend/Dockerfile.embed-lambda", "backend/Dockerfile.embed-lambda.dockerignore",
                     "backend/requirements.lock", "backend/pyproject.toml"):
            self.assertTrue(ci.select_checks([path], "pull_request")["embedder"], path)

    def test_docs_pr_can_complete_without_app_builds(self):
        self.assertFalse(any(ci.select_checks(["docs/deployment/README.md"], "pull_request").values()))

    def test_main_keeps_full_app_checks_but_skips_unrelated_arm64_build(self):
        self.assertEqual(ci.select_checks(["apps/web/src/App.tsx"], "push"), {"web": True, "backend": True, "package": False, "scripts": True, "embedder": True})

    def test_workflow_edits_and_unknown_history_run_all_checks(self):
        self.assertTrue(all(ci.select_checks([".github/workflows/checks.yml"], "pull_request").values()))
        self.assertTrue(all(ci.select_checks(None, "pull_request").values()))

    def test_initial_or_missing_base_never_skips_checks(self):
        self.assertIsNone(ci.changed_paths("0" * 40))
        self.assertIsNone(ci.changed_paths("--unsafe-option"))
        with patch.object(ci.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "git")):
            self.assertIsNone(ci.changed_paths("a" * 40))

    def test_cross_component_moves_keep_both_sides_in_the_check_selection(self):
        result = subprocess.CompletedProcess([], 0, stdout=b"backend/old.py\0apps/web/new.ts\0")
        with patch.object(ci.subprocess, "run", return_value=result) as run:
            selected = ci.select_checks(ci.changed_paths("a" * 40), "pull_request")
        self.assertIn("--no-renames", run.call_args.args[0])
        self.assertTrue(selected["web"] and selected["backend"] and selected["package"])
