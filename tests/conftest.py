"""Shared test fixtures: a temporary database and an isolated config."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db  # noqa: E402
from app.config import Config  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def base_config_data() -> dict:
    with open(REPO_ROOT / "config.yaml", "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


@pytest.fixture()
def config(tmp_path: Path, base_config_data: dict) -> Config:
    data = copy.deepcopy(base_config_data)
    data["app"]["data_dir"] = str(tmp_path / "data")
    data["app"]["db_path"] = str(tmp_path / "data" / "test.db")
    data["app"]["frames_dir"] = str(tmp_path / "data" / "frames")
    # Tests never reach the network.
    for feed in data["feeds"]:
        feed["enabled"] = feed["id"] == "demo_local"
    data["blind_spot"]["dem"]["cache_dir"] = str(tmp_path / "dem")
    return Config(data, tmp_path / "config.yaml")


@pytest.fixture()
def database(config: Config):
    db.configure(config.db_path)
    db.init_db()
    yield db
    db.execute("PRAGMA optimize")


@pytest.fixture()
def seeded(database, config):
    """A camera with a known view and a sensor inside it."""
    database.execute(
        "INSERT INTO cameras (key, feed_id, camera_id, name, lat, lon, heading, fov,"
        " mast_height, is_ptz, source, first_seen, last_seen)"
        " VALUES ('feed__cam1','feed','cam1','I-40 Rio Grande',35.1002,-106.6817,175,60,"
        " 12,1,'test','2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00')"
    )
    # ~1 km due south of the camera: inside the 175-degree, 60-degree cone.
    database.execute(
        "INSERT INTO sensors (id, name, lat, lon, source) "
        "VALUES ('TS-IN','Bosque In View',35.0912,-106.6810,'mock')"
    )
    # ~5 km north: outside the cone and outside the match radius.
    database.execute(
        "INSERT INTO sensors (id, name, lat, lon, source) "
        "VALUES ('TS-OUT','Far North',35.1450,-106.6800,'mock')"
    )
    return database
