import os
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import SecretStr, ValidationError

from wisp_backend.config import Settings


class SettingsTests(unittest.TestCase):
    def test_environment_precedence_and_no_mutation(self):
        with patch.dict(os.environ, {"XAI_API_KEY": " process-key "}, clear=True):
            with patch("wisp_backend.config.dotenv_values", return_value={
                "XAI_API_KEY": "file-key", "token_api": "legacy-key",
            }) as read:
                settings = Settings.from_env(Path("custom.env"))
            read.assert_called_once_with(Path("custom.env"))
            self.assertEqual(settings.api_key.get_secret_value(), "process-key")
            self.assertNotIn("token_api", os.environ)
            self.assertNotIn("process-key", repr(settings))

    def test_legacy_key_and_missing_key(self):
        with patch.dict(os.environ, {}, clear=True):
            for values in [{"token_api": "legacy"}, {"XAI_API_KEY": "", "token_api": "legacy"}]:
                with self.subTest(values=values), patch(
                    "wisp_backend.config.dotenv_values", return_value=values,
                ):
                    self.assertEqual(Settings.from_env().api_key.get_secret_value(), "legacy")
            for values in [{}, {"XAI_API_KEY": "   "}]:
                with self.subTest(values=values), patch(
                    "wisp_backend.config.dotenv_values", return_value=values,
                ), self.assertRaises(RuntimeError):
                    Settings.from_env()

    def test_explicit_settings_validation(self):
        for kwargs in [{"api_key": SecretStr(" ")}, {"api_key": SecretStr("key"), "request_timeout": 0}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValidationError):
                Settings(**kwargs)
