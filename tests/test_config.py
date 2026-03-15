from __future__ import annotations

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from arb.config import AppConfig, load_config


class ConfigTests(unittest.TestCase):
    def test_load_config_uses_defaults(self) -> None:
        config = load_config({})
        self.assertEqual(config, AppConfig())

    def test_load_config_reads_environment_values(self) -> None:
        config = load_config(
            {
                "ARB_ENV": "prod",
                "ARB_LOG_LEVEL": "debug",
                "ARB_TIMEZONE": "Asia/Shanghai",
                "ARB_DATA_DIR": "/tmp/arb",
                "ARB_DRY_RUN": "false",
            }
        )
        self.assertEqual(config.env, "prod")
        self.assertEqual(config.log_level, "DEBUG")
        self.assertEqual(config.timezone, "Asia/Shanghai")
        self.assertEqual(config.data_dir, Path("/tmp/arb"))
        self.assertFalse(config.dry_run)


if __name__ == "__main__":
    unittest.main()
