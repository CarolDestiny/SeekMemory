"""Package tracked Python runtime files and a prebuilt production dashboard."""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

RUNTIME_FILES = {
    "main.py",
    "metadata.yaml",
    "_conf_schema.json",
    "store/schema.sql",
    "LICENSE-MIT",
    "LICENSE-APACHE",
}
RUNTIME_PACKAGES = {"core", "store", "recall", "perceive", "maintain", "webui"}
ASSET_EXTENSIONS = {
    ".js",
    ".css",
    ".woff",
    ".woff2",
    ".ttf",
    ".svg",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".avif",
    ".ico",
}


def package_plugin(root: Path, output: Path, tag: str = "") -> Path:
    """Build a runtime-only ZIP from an explicit allowlist.

    Args:
        root: Plugin checkout containing a production build in views/memory.
        output: Destination directory for the ZIP and checksum.
        tag: Optional release tag, which must match the metadata version.

    Returns:
        Path to the installable ZIP, with plugin files at its root.

    Raises:
        ValueError: If metadata, build assets, or the release tag are invalid.
        OSError: If required files cannot be read or the archive cannot be written.
        subprocess.CalledProcessError: If Git cannot enumerate tracked files.
    """
    root = root.resolve()
    metadata = (root / "metadata.yaml").read_text(encoding="utf-8")
    version_match = re.search(
        r"^version: *[\"']?(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)[\"']? *$",
        metadata,
        re.MULTILINE,
    )
    if version_match is None:
        raise ValueError("metadata.yaml must contain a simple semantic version scalar")
    if tag and tag != f"v{version_match[1]}":
        raise ValueError(
            f"Tag {tag!r} does not match metadata version {version_match[1]}"
        )

    tracked = subprocess.check_output(
        ["git", "-C", str(root), "ls-files", "-z"], text=True, encoding="utf-8"
    ).split("\0")
    files = {
        name
        for name in tracked
        if name in RUNTIME_FILES
        or (
            Path(name).parts
            and Path(name).parts[0] in RUNTIME_PACKAGES
            and Path(name).suffix == ".py"
        )
    }
    required = RUNTIME_FILES | {f"{name}/__init__.py" for name in RUNTIME_PACKAGES}
    if missing := required - files:
        raise ValueError(f"Required runtime files are not tracked: {sorted(missing)}")

    view = root / "views/memory"
    files.update(
        {
            "views/memory/index.html",
            "views/memory/LICENSES.md",
            "views/memory/ASSET-LICENSES.txt",
        }
    )
    assets = list((view / "assets").rglob("*"))
    for asset in assets:
        if asset.is_dir():
            continue
        if asset.suffix not in ASSET_EXTENSIONS:
            raise ValueError(f"Unexpected build asset: {asset.relative_to(root)}")
        files.add(asset.relative_to(root).as_posix())
    if not any(path.suffix == ".js" for path in assets) or not any(
        path.suffix == ".css" for path in assets
    ):
        raise ValueError("Production JS and CSS are required; run pnpm build first")

    # Check before creating an output, so an incomplete build cannot be published.
    for name in sorted(files):
        path = root / name
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError(f"Symlinked runtime files are not supported: {name}")
        if not path.is_file() or path.stat().st_size == 0 and path.suffix != ".py":
            raise ValueError(f"Missing or empty runtime file: {name}")
    html = (view / "index.html").read_text(encoding="utf-8")
    references = re.findall(r'(?:src|href)="([^"#]+)"', html)
    if not references or any(
        not ref.startswith("./assets/") or f"views/memory/{ref[2:]}" not in files
        for ref in references
    ):
        raise ValueError(
            "Entry HTML must reference packaged relative production assets"
        )
    for name in files:
        if name.endswith(".css"):
            for ref in re.findall(
                r"url\([\"']?([^\"')]+)", (root / name).read_text(encoding="utf-8")
            ):
                if ref.startswith("data:"):
                    continue
                target = (root / name).parent.joinpath(ref).resolve()
                if (
                    not target.is_relative_to(root)
                    or target.relative_to(root).as_posix() not in files
                ):
                    raise ValueError(f"CSS references an unpackaged asset: {ref}")
        if name.endswith(".js") and any(
            marker in (root / name).read_text(encoding="utf-8")
            for marker in ("mock_memory_", "MockApp", "/@vite/client")
        ):
            raise ValueError(f"Development code found in production asset: {name}")

    output.mkdir(parents=True, exist_ok=True)
    archive = output / "astrbot_plugin_seekmemory.zip"
    with ZipFile(archive, "w", compression=ZIP_DEFLATED, compresslevel=9) as bundle:
        for name in sorted(files):
            # Stable timestamps and permissions keep identical inputs reproducible.
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            bundle.writestr(info, (root / name).read_bytes())
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (output / "SHA256SUMS").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    return archive


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("dist"))
    parser.add_argument("--tag", default="")
    args = parser.parse_args()
    print(package_plugin(Path(__file__).resolve().parents[1], args.output, args.tag))
