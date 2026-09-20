from pathlib import Path


def runtime_version(root_dir: Path | None = None) -> str:
    """Return the authoritative AIBA version from the repository VERSION file."""
    root = Path(root_dir) if root_dir is not None else Path(__file__).resolve().parents[1]
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    if not version:
        raise RuntimeError("VERSION file is empty")
    return version
