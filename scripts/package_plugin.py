"""打包 Git 跟踪的 Python 运行文件和已构建的生产界面。"""

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
RUNTIME_PACKAGES = {
    "app",
    "adapters",
    "core",
    "store",
    "recall",
    "perceive",
    "maintain",
    "webui",
    "orchestration",
}
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
    """按显式白名单构建仅含运行所需文件的 ZIP。

    Args:
        root: 插件源码目录，pages/memory 中需有生产构建产物。
        output: ZIP 与校验文件的输出目录。
        tag: 可选的发布标签，必须与元数据版本一致。

    Returns:
        可安装 ZIP 的路径，插件文件直接位于包根目录。

    Raises:
        ValueError: 元数据、构建资源或发布标签无效。
        OSError: 无法读取必要文件或写入安装包。
        subprocess.CalledProcessError: Git 无法列出跟踪的文件。
    """
    root = root.resolve()
    metadata = (root / "metadata.yaml").read_text(encoding="utf-8")
    version_match = re.search(
        r"^version: *[\"']?(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)[\"']? *$",
        metadata,
        re.MULTILINE,
    )
    if version_match is None:
        raise ValueError("metadata.yaml 必须包含简单的语义化版本字符串")
    if tag and tag != f"v{version_match[1]}":
        raise ValueError(f"标签 {tag!r} 与元数据版本 {version_match[1]} 不匹配")

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
        raise ValueError(f"必要运行文件未被 Git 跟踪： {sorted(missing)}")

    view = root / "pages/memory"
    files.update(
        {
            "pages/memory/index.html",
            "pages/memory/LICENSES.md",
            "pages/memory/ASSET-LICENSES.txt",
        }
    )
    assets = list((view / "assets").rglob("*"))
    for asset in assets:
        if asset.is_dir():
            continue
        if asset.suffix not in ASSET_EXTENSIONS:
            raise ValueError(f"构建资源类型不受支持： {asset.relative_to(root)}")
        files.add(asset.relative_to(root).as_posix())
    if not any(path.suffix == ".js" for path in assets) or not any(
        path.suffix == ".css" for path in assets
    ):
        raise ValueError("缺少生产 JS 或 CSS，请先运行 pnpm build")

    # 先检查再创建产物，防止发布不完整的构建。
    for name in sorted(files):
        path = root / name
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError(f"不支持符号链接或指向插件目录外的运行文件： {name}")
        if not path.is_file() or (path.stat().st_size == 0 and path.suffix != ".py"):
            raise ValueError(f"运行文件缺失或为空： {name}")
    html = (view / "index.html").read_text(encoding="utf-8")
    references = re.findall(r'(?:src|href)="([^"#]+)"', html)
    if not references or any(
        not ref.startswith("./assets/") or f"pages/memory/{ref[2:]}" not in files
        for ref in references
    ):
        raise ValueError("入口 HTML 必须通过相对路径引用已打包的生产资源")
    for name in files:
        path = root / name
        if path.suffix not in {".css", ".js"}:
            continue
        content = path.read_text(encoding="utf-8")
        if path.suffix == ".js":
            if any(
                marker in content
                for marker in ("mock_memory_", "MockApp", "/@vite/client")
            ):
                raise ValueError(f"生产资源中发现开发代码： {name}")
            continue
        references = re.findall(r"url\([\"']?([^\"')]+)", content)
        for ref in references:
            if ref.startswith("data:"):
                continue
            target = path.parent.joinpath(ref).resolve()
            if not target.is_relative_to(root):
                raise ValueError(f"CSS 引用了未打包的资源： {ref}")
            if target.relative_to(root).as_posix() not in files:
                raise ValueError(f"CSS 引用了未打包的资源： {ref}")

    output.mkdir(parents=True, exist_ok=True)
    archive = output / "astrbot_plugin_seekmemory.zip"
    with ZipFile(archive, "w", compression=ZIP_DEFLATED, compresslevel=9) as bundle:
        for name in sorted(files):
            # 固定时间戳和权限，保证相同输入可重复构建。
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
