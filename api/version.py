from pathlib import Path


def runtime_version(root_dir: Path | None = None) -> str:
    """Return the authoritative AIBA version from the repository VERSION file."""
    root = Path(root_dir) if root_dir is not None else Path(__file__).resolve().parents[1]
    version_file = root / "VERSION"
    if not version_file.is_file():
        version_file = Path(__file__).resolve().parents[1] / "VERSION"
    version = version_file.read_text(encoding="utf-8").strip()
    if not version:
        raise RuntimeError("VERSION file is empty")
    return version
