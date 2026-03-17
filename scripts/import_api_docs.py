import argparse
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import List, Optional, Set, Tuple


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_REPO_URL = "https://github.com/ShakeChanDev/api-docs.git"
DEFAULT_DEST_DIR = ROOT_DIR / "docs" / "imported" / "api-docs"
MANAGED_SUFFIXES = {".md", ".sql"}
SKIP_SOURCE_FILES = {".gitignore"}
FILE_DESCRIPTIONS = {
    "sora2api-task-chain.md": "`sora2api` 图片/视频任务链路拆解",
    "sora-observed-web-api.md": "Sora Web 侧观测接口速查",
    "camoufox-reference.md": "Camoufox 官方资料整理",
    "ixbrowser-local-api.md": "ixBrowser Local API 速查",
    "adspower-local-api.md": "AdsPower Local API 参考",
    "receipt-plus-bind-api.md": "Receipt Plus 绑定链路参考",
    "rpasora-api.md": "历史 rpaSora 接口快照",
    "webshare-proxy-core-storage.md": "Webshare 代理核心落库方案",
    "webshare-proxy-core-schema.sql": "Webshare 代理核心存储 DDL",
}


def normalize_repo_url(repo_url: str) -> str:
    if repo_url.endswith(".git"):
        return repo_url[:-4]
    return repo_url


def run_git(args: List[str], cwd: Optional[Path] = None) -> str:
    completed = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"git command failed: {' '.join(args)}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    return completed.stdout.strip()


def collect_source_files(source_dir: Path) -> List[Path]:
    files = []
    for path in source_dir.iterdir():
        if not path.is_file():
            continue
        if path.name in SKIP_SOURCE_FILES:
            continue
        if path.suffix.lower() not in MANAGED_SUFFIXES:
            continue
        files.append(path)
    return sorted(files, key=lambda item: item.name.lower())


def cleanup_destination(dest_dir: Path, incoming_names: Set[str]) -> None:
    if not dest_dir.exists():
        return

    for path in dest_dir.iterdir():
        if not path.is_file():
            continue
        if path.suffix.lower() not in MANAGED_SUFFIXES:
            continue
        if path.name == "README.md":
            continue
        if path.name in incoming_names:
            continue
        path.unlink()


def copy_source_files(source_files: List[Path], dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    for source_file in source_files:
        shutil.copy2(source_file, dest_dir / source_file.name)


def render_readme(source_files: List[Path], repo_url: str, source_commit: str) -> str:
    imported_on = date.today().isoformat()
    lines = [
        "# api-docs 导入说明",
        "",
        "这些资料从上游文档仓库导入到当前项目，目的是把分散在外部仓库的链路说明、外部依赖速查和存储设计稿沉淀到本仓库，方便本地检索和后续维护。",
        "",
        f"- 来源仓库：<{normalize_repo_url(repo_url)}>",
        f"- 来源提交：`{source_commit}`",
        f"- 导入日期：`{imported_on}`",
        "- 落库路径：`docs/imported/api-docs/`",
        "- 导入策略：保留原文件名和主体内容，不改写为当前仓库的正式接口契约",
        "",
        "## 使用边界",
        "",
        "- `sora2api-task-chain.md`、`sora-observed-web-api.md` 与当前项目关联最直接，可作为 Sora 上游链路参考。",
        "- `camoufox-reference.md`、`ixbrowser-local-api.md`、`adspower-local-api.md`、`receipt-plus-bind-api.md` 主要是外部工具或外围链路资料。",
        "- `rpasora-api.md` 以及部分文档中的 `app/...`、`docs/architecture.md`、`docs/research/...` 引用来自原始上下文，当前仓库不一定存在对应文件。",
        "- `webshare-proxy-core-schema.sql` 和 `webshare-proxy-core-storage.md` 是存储设计稿，不会自动接入当前项目现有 SQLite 结构。",
        "- 本目录是导入副本，不会自动跟踪上游仓库更新；如需重新同步，请运行 `python scripts/import_api_docs.py`。",
        "",
        "## 文件清单",
        "",
        "| 文件 | 说明 |",
        "| --- | --- |",
    ]

    for source_file in source_files:
        description = FILE_DESCRIPTIONS.get(source_file.name, "上游导入文件")
        lines.append(f"| [{source_file.name}](./{source_file.name}) | {description} |")

    lines.append("")
    return "\n".join(lines)


def import_docs(repo_url: str, dest_dir: Path, ref: Optional[str]) -> Tuple[str, List[str]]:
    with tempfile.TemporaryDirectory(prefix="api-docs-import-") as tmp_dir:
        clone_dir = Path(tmp_dir) / "upstream"
        run_git(["git", "clone", repo_url, str(clone_dir)])
        if ref:
            run_git(["git", "checkout", ref], cwd=clone_dir)

        source_commit = run_git(["git", "rev-parse", "--short", "HEAD"], cwd=clone_dir)
        source_files = collect_source_files(clone_dir)
        incoming_names = {path.name for path in source_files}

        cleanup_destination(dest_dir, incoming_names)
        copy_source_files(source_files, dest_dir)
        readme_path = dest_dir / "README.md"
        readme_path.write_text(
            render_readme(source_files, repo_url=repo_url, source_commit=source_commit),
            encoding="utf-8",
        )
        return source_commit, sorted(incoming_names)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import upstream api-docs files into docs/imported/api-docs."
    )
    parser.add_argument("--repo-url", default=DEFAULT_REPO_URL, help="Upstream git repository URL.")
    parser.add_argument(
        "--dest-dir",
        default=str(DEFAULT_DEST_DIR),
        help="Destination directory for imported files.",
    )
    parser.add_argument(
        "--ref",
        default=None,
        help="Optional git ref to checkout after clone. Defaults to upstream default branch HEAD.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dest_dir = Path(args.dest_dir).resolve()
    source_commit, imported_files = import_docs(
        repo_url=args.repo_url,
        dest_dir=dest_dir,
        ref=args.ref,
    )
    print(f"Imported {len(imported_files)} files from {args.repo_url} @ {source_commit}")
    for name in imported_files:
        print(f"- {name}")
    print(f"README refreshed: {dest_dir / 'README.md'}")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
