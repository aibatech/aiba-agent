from pathlib import Path


def runtime_version(root_dir: Path) -> str:
    """Return the authoritative AIBA version from the repository VERSION file."""
    version = (Path(root_dir) / "VERSION").read_text(encoding="utf-8").strip()
    if not version:
        raise RuntimeError("VERSION file is empty")
    return version
