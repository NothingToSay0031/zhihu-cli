"""Publish markdown files as Zhihu articles: single file or whole folder."""

from __future__ import annotations

import hashlib
import json
import sys
from contextlib import contextmanager
from pathlib import Path

import click

from .. import config
from ..auth import cookie_str_to_dict, get_cookie_string
from ..display import print_error, print_hint, print_info, print_success, print_warning
from ..markdown import extract_local_images, md_to_html
from ..split import part_title, series_lead, split_markdown

PUBLISHED_FILE_NAME = "published.json"


@contextmanager
def _get_client():
    from ..client import ZhihuClient

    cookie = get_cookie_string()
    if not cookie:
        print_error("Not authenticated - run [bold]zhihu login[/bold]")
        sys.exit(1)
    with ZhihuClient(cookie_str_to_dict(cookie)) as client:
        yield client


def _published_path() -> Path:
    return config.CONFIG_DIR / PUBLISHED_FILE_NAME


def _load_published() -> dict:
    path = _published_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_published(data: dict) -> None:
    path = _published_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _part_ids(state: dict | None) -> list[str]:
    if not state:
        return []
    parts = state.get("parts")
    if isinstance(parts, list) and parts:
        return [str(p["article_id"]) for p in parts if p.get("article_id")]
    article_id = state.get("article_id", "")
    return [str(article_id)] if article_id else []


def _record(base_title: str, results: list[tuple[str, str]], sha256: str) -> dict:
    return {
        "sha256": sha256,
        "article_id": results[0][1] if results else "",
        "title": base_title,
        "parts": [{"title": title, "article_id": aid} for title, aid in results],
    }


def _print_part_urls(results: list[tuple[str, str]], *, success: bool = False) -> None:
    printer = print_success if success else print_hint
    for i, (title, article_id) in enumerate(results, 1):
        printer(
            f"  Part {i}: [bold]{title}[/bold]\n"
            f"    https://zhuanlan.zhihu.com/p/{article_id}"
        )


def _upload_images(client, text: str, base_dir: Path) -> dict[str, dict]:
    image_map: dict[str, dict] = {}
    for ref, img_path in extract_local_images(text, base_dir).items():
        try:
            image_map[ref] = client.upload_image(str(img_path), source="article")
            print_info(f"  Uploaded image: {img_path.name}")
        except Exception as e:
            print_warning(f"  Image upload failed ({img_path.name}): {e}")
    return image_map


def _ensure_html_budget(parts: list[str], image_map: dict[str, dict]) -> list[str]:
    """Re-split any part whose converted HTML still exceeds the Zhihu-safe size."""
    out: list[str] = []
    for part in parts:
        html = md_to_html(part, image_map)
        too_big = len(html.encode("utf-8")) > config.MAX_PART_HTML_BYTES
        if not too_big or len(part) < 4_000:
            out.append(part)
            continue
        budget = max(len(part) // 2, 4_000)
        smaller = split_markdown(part, budget)
        if smaller == [part]:
            out.append(part)
            continue
        out.extend(_ensure_html_budget(smaller, image_map))
    return out or parts


def _prepare_parts(
    client, md_path: Path, *, no_split: bool = False
) -> tuple[str, dict[str, dict], list[str]]:
    text = md_path.read_text(encoding="utf-8")
    image_map = _upload_images(client, text, md_path.parent)
    if no_split:
        return md_path.stem, image_map, [text]
    parts = _ensure_html_budget(split_markdown(text), image_map)
    return md_path.stem, image_map, parts


def _create_one(client, title: str, html: str, topics: list[str]) -> str:
    result = client.create_article(
        title=title, content=html, topic_ids=list(topics) if topics else None
    )
    article_id = result.get("id", "")
    if not article_id:
        raise RuntimeError("Article published but no ID returned")
    return str(article_id)


def _warn_large_html(html: str) -> None:
    size_kb = len(html.encode("utf-8")) // 1024
    if size_kb >= 400:
        print_warning(
            f"Article HTML is {size_kb} KB; Zhihu draft upload may take a few minutes"
        )


def _publish_parts(
    client,
    md_path: Path,
    topics: list[str],
    existing_ids: list[str],
    *,
    progress_key: str | None = None,
    no_split: bool = False,
) -> tuple[str, list[tuple[str, str]]]:
    """Publish or update all parts of a markdown file.

    ``existing_ids`` are reused in order (in-place update); extra parts are
    created. Progress is saved after each part when ``progress_key`` is set,
    so a mid-series failure can resume without duplicating earlier parts.
    """
    base_title, image_map, parts = _prepare_parts(client, md_path, no_split=no_split)
    n = len(parts)
    if no_split:
        print_warning(
            "Publishing as a single article (--no-split); "
            "Zhihu may reject very large drafts"
        )
    elif n > 1:
        print_info(f"Splitting into {n} parts")
    results: list[tuple[str, str]] = []
    for i, part_md in enumerate(parts, 1):
        title = part_title(base_title, i, n)
        html = md_to_html(series_lead(base_title, i, n) + part_md, image_map)
        _warn_large_html(html)
        print_info(f"  Part {i}/{n}: {title}")
        if i <= len(existing_ids) and existing_ids[i - 1]:
            article_id = existing_ids[i - 1]
            client.update_article(
                article_id=article_id,
                title=title,
                content=html,
                topic_ids=list(topics) if topics else None,
            )
        else:
            article_id = _create_one(client, title, html, topics)
        results.append((title, article_id))
        if progress_key is not None:
            published = _load_published()
            published[progress_key] = _record(base_title, results, sha256="")
            _save_published(published)
    return base_title, results


def publish_markdown(
    client,
    md_path: Path,
    topics: list[str],
    existing_ids: list[str] | None = None,
    *,
    no_split: bool = False,
) -> tuple[str, list[tuple[str, str]]]:
    """Publish one markdown file (split if large). Returns (base_title, parts)."""
    return _publish_parts(
        client, md_path, topics, existing_ids or [], no_split=no_split
    )


@click.command("publish-md")
@click.argument("file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("-t", "--topic", "topics", multiple=True, help="Topic ID (repeatable)")
@click.option("--force", is_flag=True, help="Republish even if unchanged since last run")
@click.option(
    "--no-split",
    is_flag=True,
    help="Do not split a large file; publish as one article (may fail on Zhihu)",
)
def publish_md(file: Path, topics: tuple[str, ...], force: bool, no_split: bool):
    """Publish a single markdown file as an article (发布单个 Markdown 文章)."""
    key = str(file)
    h = _file_hash(file)
    published = _load_published()
    state = published.get(key)
    if state and state.get("sha256") == h and not force:
        print_hint(
            f"Already published (unchanged, id={state.get('article_id', '?')}): {file.name}"
        )
        parts = state.get("parts")
        if isinstance(parts, list) and parts:
            _print_part_urls(
                [(p.get("title", ""), str(p.get("article_id", ""))) for p in parts]
            )
        else:
            print_hint(f"  https://zhuanlan.zhihu.com/p/{state.get('article_id')}")
        return
    reuse: list[str] = []
    if not force and state and not state.get("sha256"):
        reuse = _part_ids(state)
        if reuse:
            print_info(f"Resuming incomplete publish ({len(reuse)} part(s) already uploaded)")
    try:
        with _get_client() as client:
            title, results = _publish_parts(
                client,
                file,
                list(topics),
                reuse,
                progress_key=key,
                no_split=no_split,
            )
        published = _load_published()
        published[key] = _record(title, results, h)
        _save_published(published)
        if len(results) == 1:
            part_title_text, article_id = results[0]
            print_success(
                f"Article published!  [bold]{part_title_text}[/bold]\n"
                f"  ID: [bold]{article_id}[/bold]\n"
                f"  https://zhuanlan.zhihu.com/p/{article_id}"
            )
        else:
            print_success(f"Published {len(results)} parts of [bold]{title}[/bold]")
            _print_part_urls(results, success=True)
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
@click.option(
    "--no-split",
    is_flag=True,
    help="Do not split large files; publish each as one article (may fail on Zhihu)",
)
def publish_dir(
    directory: Path,
    topics: tuple[str, ...],
    pattern: str,
    recursive: bool,
    dry_run: bool,
    force: bool,
    update: bool,
    no_split: bool,
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
            n_parts = (
                1 if no_split else len(split_markdown(f.read_text(encoding="utf-8")))
            )
            part_note = f" ({n_parts} parts)" if n_parts > 1 else ""
            if state and state.get("sha256") == h and not force and not update:
                print_hint(f"  [skip] (unchanged) {f.name}{part_note}")
            elif state and update and not force:
                print_info(f"  [update] {f.name}{part_note}")
            elif state:
                print_info(f"  [republish] {f.name}{part_note}")
            else:
                print_info(f"  [new] {f.name}{part_note}")
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
        reuse: list[str] = []
        if update and not force:
            reuse = _part_ids(state)
        elif not force and state and not state.get("sha256"):
            reuse = _part_ids(state)
        action = "update" if reuse and update else "publish"
        print_info(f"[{action}] {f.name}")
        try:
            with _get_client() as client:
                title, results = _publish_parts(
                    client,
                    f,
                    list(topics),
                    reuse,
                    progress_key=key,
                    no_split=no_split,
                )
            published = _load_published()
            published[key] = _record(title, results, h)
            _save_published(published)
            if len(results) == 1:
                print_success(
                    f"  OK  {results[0][0]}  ->  https://zhuanlan.zhihu.com/p/{results[0][1]}"
                )
            else:
                print_success(f"  OK  {title}  ({len(results)} parts)")
                _print_part_urls(results, success=True)
            ok += 1
        except Exception as e:
            print_error(f"  FAIL {f.name}: {e}")
            failed += 1

    print_success(f"\nDone: {ok} published, {skipped} skipped, {failed} failed")


def update_markdown(
    client,
    md_path: Path,
    article_id: str,
    topics: list[str],
    *,
    no_split: bool = False,
) -> tuple[str, list[tuple[str, str]]]:
    """Update an article from markdown. Extra parts are published as new articles."""
    return _publish_parts(
        client,
        md_path,
        topics,
        [article_id] if article_id else [],
        no_split=no_split,
    )


@click.command("update-md")
@click.argument("file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--article-id", required=True, help="ID of the existing article to update")
@click.option("-t", "--topic", "topics", multiple=True, help="Topic ID (repeatable)")
@click.option(
    "--no-split",
    is_flag=True,
    help="Do not split a large file; update as one article (may fail on Zhihu)",
)
def update_md(
    file: Path, article_id: str, topics: tuple[str, ...], no_split: bool
):
    """Update an existing article from a markdown file, keeping its ID (原地更新文章)."""
    try:
        with _get_client() as client:
            title, results = update_markdown(
                client, file, article_id, list(topics), no_split=no_split
            )
        published = _load_published()
        published[str(file)] = _record(title, results, _file_hash(file))
        _save_published(published)
        if len(results) == 1:
            print_success(
                f"Article updated!  [bold]{results[0][0]}[/bold]\n"
                f"  ID: [bold]{results[0][1]}[/bold]\n"
                f"  https://zhuanlan.zhihu.com/p/{results[0][1]}"
            )
        else:
            print_success(
                f"Updated/published {len(results)} parts of [bold]{title}[/bold]"
            )
            _print_part_urls(results, success=True)
    except Exception as e:
        print_error(f"Failed to update article: {e}")
        sys.exit(1)
