import importlib.util
import json
from io import BytesIO
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location("bootstrap_database", Path(__file__).parents[1] / "bootstrap_database.py")
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)
ARGS = ["bootstrap_database.py", "--function", "migrate", "--secret-arn", "master", "--credentials-secret-arn", "credentials"]
APP, MIGRATOR, EMBEDDER = "a" * 64, "b" * 64, "c" * 64


class Bootstrap(unittest.TestCase):
    def run_main(self, stored, extra=()):
        calls = []
        store, client = Mock(), Mock()

        def get_secret_value(SecretId):
            return {"SecretString": json.dumps(stored if SecretId == "credentials" else {"username": "jobhunter_admin", "password": "admin"})}

        def persist(**kwargs):
            calls.append(("persist", json.loads(kwargs["SecretString"])))

        def invoke(**kwargs):
            calls.append(("invoke", json.loads(kwargs["Payload"])))
            return {"Payload": BytesIO(b'{"status":"migrated"}')}

        store.get_secret_value.side_effect = get_secret_value
        store.put_secret_value.side_effect = persist
        client.invoke.side_effect = invoke
        with patch("sys.argv", ARGS + list(extra)), patch.object(bootstrap.boto3, "client", side_effect=[client, store]), patch("builtins.print"):
            bootstrap.main()
        return calls

    def test_the_embedding_role_is_not_touched_unless_asked_for(self):
        calls = self.run_main({"jobhunter_app": APP, "jobhunter_migrator": MIGRATOR, "jobhunter_embedder": EMBEDDER})
        self.assertEqual([name for name, _ in calls], ["invoke"])      # nothing persisted
        self.assertEqual(set(calls[0][1]["passwords"]), {"jobhunter_app", "jobhunter_migrator"})   # an older migration function stays compatible

    def test_asking_for_it_generates_a_password_and_persists_it_before_invoking(self):
        calls = self.run_main({"jobhunter_app": APP, "jobhunter_migrator": MIGRATOR}, ["--embedder"])
        self.assertEqual([name for name, _ in calls], ["persist", "invoke"])
        generated = calls[0][1]["jobhunter_embedder"]
        self.assertGreaterEqual(len(generated), 32)
        self.assertEqual(calls[1][1]["passwords"]["jobhunter_embedder"], generated)
        self.assertEqual(calls[1][1]["passwords"]["jobhunter_app"], APP)      # existing passwords are reused, not rotated

    def test_an_existing_embedding_password_is_reused(self):
        calls = self.run_main({"jobhunter_app": APP, "jobhunter_migrator": MIGRATOR, "jobhunter_embedder": EMBEDDER}, ["--embedder"])
        self.assertEqual([name for name, _ in calls], ["invoke"])
        self.assertEqual(calls[0][1]["passwords"]["jobhunter_embedder"], EMBEDDER)


if __name__ == "__main__":
    unittest.main()
