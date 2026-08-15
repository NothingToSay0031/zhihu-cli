"""Publish markdown files as Zhihu articles: single file or whole folder."""

from __future__ import annotations

import hashlib
import json
import sys
from contextlib import contextmanager
from pathlib import Path

import click

from ..auth import cookie_str_to_dict, get_cookie_string
from ..config import CONFIG_DIR
from ..display import print_error, print_hint, print_info, print_success, print_warning
from ..markdown import extract_local_images, md_to_html

PUBLISHED_FILE = CONFIG_DIR / "published.json"


@contextmanager
def _get_client():
    from ..client import ZhihuClient

    cookie = get_cookie_string()
    if not cookie:
        print_error("Not authenticated - run [bold]zhihu login[/bold]")
        sys.exit(1)
    with ZhihuClient(cookie_str_to_dict(cookie)) as client:
        yield client


def _load_published() -> dict:
    if not PUBLISHED_FILE.exists():
        return {}
    try:
        return json.loads(PUBLISHED_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_published(data: dict) -> None:
    PUBLISHED_FILE.parent.mkdir(parents=True, exist_ok=True)
    PUBLISHED_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _md_to_article(client, md_path: Path) -> tuple[str, str]:
    """Convert a markdown file to (title, html).

    Article title is taken from the file name (stem) instead of the first
    heading in the body: in-place headings may be absent or may be matched
    inside fenced code blocks (e.g. a ``# Cargo.toml`` line), which would
    produce a wrong title and truncate the body.
    """
    text = md_path.read_text(encoding="utf-8")
    title = md_path.stem

    image_map: dict[str, dict] = {}
    local_images = extract_local_images(text, md_path.parent)
    for ref, img_path in local_images.items():
        try:
            info = client.upload_image(str(img_path), source="article")
            image_map[ref] = info
            print_info(f"  Uploaded image: {img_path.name}")
        except Exception as e:
            print_warning(f"  Image upload failed ({img_path.name}): {e}")

    return title, md_to_html(text, image_map)


def publish_markdown(client, md_path: Path, topics: list[str]) -> tuple[str, str]:
    """Publish one markdown file. Returns (title, article_id)."""
    title, html = _md_to_article(client, md_path)
    result = client.create_article(
        title=title, content=html, topic_ids=list(topics) if topics else None
    )
    article_id = result.get("id", "")
    if not article_id:
        raise RuntimeError("Article published but no ID returned")
    return title, str(article_id)


@click.command("publish-md")
@click.argument("file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("-t", "--topic", "topics", multiple=True, help="Topic ID (repeatable)")
@click.option("--force", is_flag=True, help="Republish even if unchanged since last run")
def publish_md(file: Path, topics: tuple[str, ...], force: bool):
    """Publish a single markdown file as an article (发布单个 Markdown 文章)."""
    key = str(file)
    h = _file_hash(file)
    published = _load_published()
    state = published.get(key)
    if state and state.get("sha256") == h and not force:
        print_hint(
            f"Already published (unchanged, id={state.get('article_id', '?')}): {file.name}"
        )
        print_hint(f"  https://zhuanlan.zhihu.com/p/{state.get('article_id')}")
        return
    try:
        with _get_client() as client:
            title, article_id = publish_markdown(client, file, list(topics))
        published[key] = {"sha256": h, "article_id": article_id, "title": title}
        _save_published(published)
        print_success(
            f"Article published!  [bold]{title}[/bold]\n"
            f"  ID: [bold]{article_id}[/bold]\n"
            f"  https://zhuanlan.zhihu.com/p/{article_id}"
        )
    except Exception as e:
        print_error(f"Failed to publish article: {e}")
        sys.exit(1)


@click.command("publish-dir")
@click.argument("directory", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("-t", "--topic", "topics", multiple=True, help="Topic ID (repeatable)")
@click.option("--pattern", default="*.md", show_default=True, help="File glob pattern")
@click.option("-r", "--recursive", is_flag=True, help="Scan subdirectories too")
@click.option("--dry-run", is_flag=True, help="Show what would be published, publish nothing")
@click.option("--force", is_flag=True, help="Republish even if unchanged since last run")
@click.option("--update", is_flag=True, help="Update existing articles in place (keep IDs)")
def publish_dir(
    directory: Path,
    topics: tuple[str, ...],
    pattern: str,
    recursive: bool,
    dry_run: bool,
    force: bool,
    update: bool,
):
    """Publish all markdown files in a directory (批量发布文件夹中的 Markdown)."""
    if recursive:
        files = sorted(directory.rglob(pattern))
    else:
        files = sorted(directory.glob(pattern))
    files = [f for f in files if f.is_file()]
    if not files:
        print_warning(f"No files matching '{pattern}' in {directory}")
        sys.exit(1)

    published = _load_published()
    print_info(f"Found {len(files)} markdown file(s) in {directory}")

    if dry_run:
        for f in files:
            key = str(f)
            h = _file_hash(f)
            state = published.get(key)
            if state and state.get("sha256") == h and not force and not update:
                print_hint(f"  [skip] (unchanged) {f.name}")
            elif state and update and not force:
                print_info(f"  [update] {f.name}")
            elif state:
                print_info(f"  [republish] {f.name}")
            else:
                print_info(f"  [new] {f.name}")
        return

    ok = skipped = failed = 0
    for f in files:
        key = str(f)
        h = _file_hash(f)
        state = published.get(key)
        if state and state.get("sha256") == h and not force and not update:
            print_hint(f"[skip] (unchanged, id={state.get('article_id', '?')}) {f.name}")
            skipped += 1
            continue
        article_id = state.get("article_id", "") if state else ""
        if update and article_id and not force:
            print_info(f"[update] {f.name}")
            try:
                with _get_client() as client:
                    title = update_markdown(client, f, article_id, list(topics))
                published[key] = {"sha256": h, "article_id": article_id, "title": title}
                _save_published(published)
                print_success(f"  OK  {title}  ->  https://zhuanlan.zhihu.com/p/{article_id}")
                ok += 1
            except Exception as e:
                print_error(f"  FAIL {f.name}: {e}")
                failed += 1
            continue
        print_info(f"[publish] {f.name}")
        try:
            with _get_client() as client:
                title, article_id = publish_markdown(client, f, list(topics))
            published[key] = {"sha256": h, "article_id": article_id, "title": title}
            _save_published(published)
            print_success(f"  OK  {title}  ->  https://zhuanlan.zhihu.com/p/{article_id}")
            ok += 1
        except Exception as e:
            print_error(f"  FAIL {f.name}: {e}")
            failed += 1

    print_success(f"\nDone: {ok} published, {skipped} skipped, {failed} failed")


def update_markdown(
    client, md_path: Path, article_id: str, topics: list[str]
) -> str:
    """Update an existing article from a markdown file in place. Returns title."""
    title, html = _md_to_article(client, md_path)
    client.update_article(
        article_id=article_id,
        title=title,
        content=html,
        topic_ids=list(topics) if topics else None,
    )
    return title


@click.command("update-md")
@click.argument("file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--article-id", required=True, help="ID of the existing article to update")
@click.option("-t", "--topic", "topics", multiple=True, help="Topic ID (repeatable)")
def update_md(file: Path, article_id: str, topics: tuple[str, ...]):
    """Update an existing article from a markdown file, keeping its ID (原地更新文章)."""
    try:
        with _get_client() as client:
            title = update_markdown(client, file, article_id, list(topics))
        print_success(
            f"Article updated!  [bold]{title}[/bold]\n"
            f"  ID: [bold]{article_id}[/bold]\n"
            f"  https://zhuanlan.zhihu.com/p/{article_id}"
        )
    except Exception as e:
        print_error(f"Failed to update article: {e}")
        sys.exit(1)
