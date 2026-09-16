from pathlib import Path


def runtime_version(root_dir: Path) -> str:
    """Return the authoritative AIBA version from the repository VERSION file."""
    return (Path(root_dir) / "VERSION").read_text(encoding="utf-8").strip()
