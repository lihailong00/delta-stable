from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from arb.config import AppConfig, load_config

class TestConfig:

    def test_load_config_uses_defaults(self) -> None:
        config = load_config({})
        assert config == AppConfig()

    def test_load_config_reads_environment_values(self) -> None:
        config = load_config({'ARB_ENV': 'prod', 'ARB_LOG_LEVEL': 'debug', 'ARB_TIMEZONE': 'Asia/Shanghai', 'ARB_DATA_DIR': '/tmp/arb', 'ARB_DRY_RUN': 'false'})
        assert config.env == 'prod'
        assert config.log_level == 'DEBUG'
        assert config.timezone == 'Asia/Shanghai'
        assert config.data_dir == Path('/tmp/arb')
        assert not config.dry_run
