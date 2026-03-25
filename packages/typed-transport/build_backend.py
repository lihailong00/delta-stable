"""Minimal local build backend for the typed-transport package."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import tarfile
import tomllib
import zipfile
from email.message import Message
from pathlib import Path
from typing import Any

PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parent.parent
SOURCE_PACKAGE = REPO_ROOT / "src" / "typed_transport"
PYPROJECT_PATH = PACKAGE_DIR / "pyproject.toml"


def _project() -> dict[str, Any]:
    with PYPROJECT_PATH.open("rb") as handle:
        payload = tomllib.load(handle)
    return payload["project"]


def _dist_name() -> str:
    return str(_project()["name"]).replace("-", "_")


def _version() -> str:
    return str(_project()["version"])


def _wheel_name() -> str:
    return f"{_dist_name()}-{_version()}-py3-none-any.whl"


def _sdist_name() -> str:
    return f"{_dist_name()}-{_version()}.tar.gz"


def _dist_info_dir() -> str:
    return f"{_dist_name()}-{_version()}.dist-info"


def _metadata_text() -> str:
    project = _project()
    message = Message()
    message["Metadata-Version"] = "2.1"
    message["Name"] = project["name"]
    message["Version"] = project["version"]
    message["Summary"] = project["description"]
    message["Requires-Python"] = project["requires-python"]
    license_value = project.get("license")
    if isinstance(license_value, str):
        message["License"] = license_value
    for dependency in project.get("dependencies", []):
        message["Requires-Dist"] = dependency
    for key, value in project.get("urls", {}).items():
        message["Project-URL"] = f"{key}, {value}"
    readme = PACKAGE_DIR / str(project["readme"])
    if readme.exists():
        body = readme.read_text(encoding="utf-8")
        return f"{message.as_string()}\n\n{body}\n"
    return f"{message.as_string()}\n"


def _wheel_text() -> str:
    return "\n".join(
        [
            "Wheel-Version: 1.0",
            "Generator: typed-transport-local-backend",
            "Root-Is-Purelib: true",
            "Tag: py3-none-any",
            "",
        ]
    )


def _pkg_info_text() -> str:
    return _metadata_text()


def _iter_package_files() -> list[tuple[Path, str]]:
    files: list[tuple[Path, str]] = []
    for path in sorted(SOURCE_PACKAGE.rglob("*")):
        if path.is_file():
            relative = path.relative_to(REPO_ROOT / "src").as_posix()
            files.append((path, relative))
    return files


def _record_row(path: str, content: bytes) -> tuple[str, str, str]:
    digest = hashlib.sha256(content).digest()
    encoded = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return path, f"sha256={encoded}", str(len(content))


def get_requires_for_build_wheel(config_settings: dict[str, object] | None = None) -> list[str]:
    return []


def get_requires_for_build_sdist(config_settings: dict[str, object] | None = None) -> list[str]:
    return []


def prepare_metadata_for_build_wheel(
    metadata_directory: str,
    config_settings: dict[str, object] | None = None,
) -> str:
    dist_info = Path(metadata_directory) / _dist_info_dir()
    dist_info.mkdir(parents=True, exist_ok=True)
    (dist_info / "METADATA").write_text(_metadata_text(), encoding="utf-8")
    (dist_info / "WHEEL").write_text(_wheel_text(), encoding="utf-8")
    return dist_info.name


def build_wheel(
    wheel_directory: str,
    config_settings: dict[str, object] | None = None,
    metadata_directory: str | None = None,
) -> str:
    target_dir = Path(wheel_directory)
    target_dir.mkdir(parents=True, exist_ok=True)
    wheel_path = target_dir / _wheel_name()
    dist_info_dir = _dist_info_dir()
    metadata = _metadata_text().encode("utf-8")
    wheel = _wheel_text().encode("utf-8")
    records: list[tuple[str, str, str]] = []

    with zipfile.ZipFile(wheel_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for source_path, archive_path in _iter_package_files():
            content = source_path.read_bytes()
            archive.writestr(archive_path, content)
            records.append(_record_row(archive_path, content))

        metadata_path = f"{dist_info_dir}/METADATA"
        archive.writestr(metadata_path, metadata)
        records.append(_record_row(metadata_path, metadata))

        wheel_path_in_archive = f"{dist_info_dir}/WHEEL"
        archive.writestr(wheel_path_in_archive, wheel)
        records.append(_record_row(wheel_path_in_archive, wheel))

        record_path = f"{dist_info_dir}/RECORD"
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        for row in records:
            writer.writerow(row)
        writer.writerow((record_path, "", ""))
        archive.writestr(record_path, buffer.getvalue().encode("utf-8"))

    return wheel_path.name


def build_sdist(
    sdist_directory: str,
    config_settings: dict[str, object] | None = None,
) -> str:
    target_dir = Path(sdist_directory)
    target_dir.mkdir(parents=True, exist_ok=True)
    sdist_path = target_dir / _sdist_name()
    root_name = f"{_dist_name()}-{_version()}"

    with tarfile.open(sdist_path, "w:gz") as archive:
        for source_path, _archive_path in _iter_package_files():
            archive.add(source_path, arcname=f"{root_name}/src/{source_path.relative_to(REPO_ROOT / 'src').as_posix()}")
        archive.add(PYPROJECT_PATH, arcname=f"{root_name}/pyproject.toml")
        archive.add(PACKAGE_DIR / "README.md", arcname=f"{root_name}/README.md")
        archive.add(PACKAGE_DIR / "LICENSE", arcname=f"{root_name}/LICENSE")
        archive.add(PACKAGE_DIR / "build_backend.py", arcname=f"{root_name}/build_backend.py")
        for example in sorted((PACKAGE_DIR / "examples").glob("*.py")):
            archive.add(example, arcname=f"{root_name}/examples/{example.name}")

        pkg_info = _pkg_info_text().encode("utf-8")
        info = tarfile.TarInfo(name=f"{root_name}/PKG-INFO")
        info.size = len(pkg_info)
        archive.addfile(info, io.BytesIO(pkg_info))

    return sdist_path.name
