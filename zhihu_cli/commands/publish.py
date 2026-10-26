"""Publish markdown files as Zhihu articles: single file or whole folder."""

from __future__ import annotations

import hashlib
import json
import sys
import time
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


def _find_record(published: dict, md_path: Path) -> tuple[str, dict | None]:
    """Return ``(key, state)`` for a file: exact path, else a unique same-stem record.

    A moved or renamed folder must not silently turn an update into a duplicate
    series, so a record whose title matches the file stem counts as the same work.
    An ambiguous match (several files with the same stem) returns no state.
    """
    key = str(md_path)
    state = published.get(key)
    if state:
        return key, state
    candidates = [
        (k, v)
        for k, v in published.items()
        if (v.get("title") or Path(k).stem) == md_path.stem
    ]
    if len(candidates) == 1:
        return candidates[0]
    return key, None


def _print_part_urls(results: list[tuple[str, str]], *, success: bool = False) -> None:
    printer = print_success if success else print_hint
    for i, (title, article_id) in enumerate(results, 1):
        printer(
            f"  Part {i}: [bold]{title}[/bold]\n"
            f"    https://zhuanlan.zhihu.com/p/{article_id}"
        )


def _upload_images(client, text: str, base_dir: Path) -> dict[str, dict]:
    """Upload local images, trying each one up to IMAGE_UPLOAD_ATTEMPTS times.

    A failed image is replaced by its alt text and the article is still written.
    Re-running the command retries the images that were left out.
    """
    images = extract_local_images(text, base_dir)
    image_map: dict[str, dict] = {}
    failures: list[tuple[str, str]] = []
    total = len(images)
    for index, (ref, img_path) in enumerate(images.items(), 1):
        print_info(f"  Uploading image {index}/{total}: {img_path.name}")
        last_error = ""
        for attempt in range(1, config.IMAGE_UPLOAD_ATTEMPTS + 1):
            try:
                image_map[ref] = client.upload_image(str(img_path), source="article")
                print_info(f"  Uploaded image: {img_path.name}")
                break
            except Exception as e:
                last_error = str(e)
                if attempt < config.IMAGE_UPLOAD_ATTEMPTS:
                    delay = config.IMAGE_RETRY_BACKOFF * (2 ** (attempt - 1))
                    print_warning(
                        f"  Image upload failed ({img_path.name}), "
                        f"attempt {attempt}/{config.IMAGE_UPLOAD_ATTEMPTS}, "
                        f"retrying in {delay:.0f}s: {e}"
                    )
                    time.sleep(delay)
        else:
            failures.append((img_path.name, last_error))
            print_warning(
                f"  Image upload failed after {config.IMAGE_UPLOAD_ATTEMPTS} "
                f"attempts ({img_path.name}); leaving it out: {last_error}"
            )
    if failures:
        names = ", ".join(name for name, _ in failures)
        print_warning(
            f"  {len(failures)} image(s) left out ({names}); "
            "the article will still be updated. Re-run the command to retry."
        )
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


def _upsert_part(
    client,
    base_title: str,
    image_map: dict[str, dict],
    part_md: str,
    index: int,
    total: int,
    topics: list[str],
    existing_ids: list[str],
) -> tuple[str, str]:
    """Write one part: update the recorded article at ``index``, else create it."""
    title = part_title(base_title, index, total)
    html = md_to_html(series_lead(base_title, index, total) + part_md, image_map)
    _warn_large_html(html)
    print_info(f"  Part {index}/{total}: {title}")
    if index <= len(existing_ids) and existing_ids[index - 1]:
        article_id = existing_ids[index - 1]
        client.update_article(
            article_id=article_id,
            title=title,
            content=html,
            topic_ids=list(topics) if topics else None,
        )
    else:
        article_id = _create_one(client, title, html, topics)
    return title, article_id


def _announce(n: int, no_split: bool) -> None:
    if no_split:
        print_warning(
            "Publishing as a single article (--no-split); "
            "Zhihu may reject very large drafts"
        )
    elif n > 1:
        print_info(f"Splitting into {n} parts")


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
    _announce(n, no_split)
    results: list[tuple[str, str]] = []
    for i, part_md in enumerate(parts, 1):
        results.append(
            _upsert_part(
                client, base_title, image_map, part_md, i, n, topics, existing_ids
            )
        )
        if progress_key is not None:
            published = _load_published()
            published[progress_key] = _record(base_title, results, sha256="")
            _save_published(published)
    return base_title, results


def reconcile_markdown(
    client,
    md_path: Path,
    existing_ids: list[str],
    topics: list[str],
    *,
    no_split: bool = False,
    prune_extra: bool = True,
    assume_yes: bool = False,
) -> tuple[str, list[tuple[str, str]], list[str], int]:
    """Update a series from markdown, keeping the part count in sync with the file.

    Recorded IDs are reused in order, new parts are created, and tail articles
    left over by a shorter split are deleted when ``prune_extra`` is set. Deletion
    happens only after every part is written, so a mid-series failure cannot
    destroy the tail of the previous version.
    """
    base_title, image_map, parts = _prepare_parts(client, md_path, no_split=no_split)
    n = len(parts)
    _announce(n, no_split)
    surplus = existing_ids[n:]
    if surplus:
        if not prune_extra:
            print_warning(
                f"新的切分只有 {n} 篇，保留原有的 {len(surplus)} 篇尾部文章（--keep-extra）"
            )
        else:
            print_warning(
                f"新的切分只有 {n} 篇，原系列多出 {len(surplus)} 篇尾部文章"
            )
            if not assume_yes:
                click.confirm("删除多出的文章？此操作不可撤销", abort=True)
    results: list[tuple[str, str]] = []
    created = 0
    for i, part_md in enumerate(parts, 1):
        if not (i <= len(existing_ids) and existing_ids[i - 1]):
            created += 1
        results.append(
            _upsert_part(
                client, base_title, image_map, part_md, i, n, topics, existing_ids
            )
        )
    deleted: list[str] = []
    if prune_extra:
        for article_id in surplus:
            if client.delete_article(article_id):
                deleted.append(article_id)
            else:
                print_warning(f"未能删除多余文章 {article_id}")
    return base_title, results, deleted, created


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
    if not state:
        matched_key, matched = _find_record(published, file)
        if matched:
            print_warning(
                f"同名文章已从 {matched_key} 发布过"
                f"（{len(_part_ids(matched))} 篇）；原地更新请用 "
                "[bold]zhihu update-md[/bold]"
            )
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
    article_ids: list[str],
    topics: list[str],
    *,
    no_split: bool = False,
    prune_extra: bool = True,
    assume_yes: bool = False,
) -> tuple[str, list[tuple[str, str]], list[str], int]:
    """Update a series from markdown, reusing ``article_ids`` in part order."""
    return reconcile_markdown(
        client,
        md_path,
        article_ids,
        topics,
        no_split=no_split,
        prune_extra=prune_extra,
        assume_yes=assume_yes,
    )


@click.command("update-md")
@click.argument("file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--article-id",
    "article_ids",
    multiple=True,
    help="Existing part article IDs in part order (repeatable). "
    "Defaults to the IDs recorded for this file.",
)
@click.option("-t", "--topic", "topics", multiple=True, help="Topic ID (repeatable)")
@click.option(
    "--no-split",
    is_flag=True,
    help="Do not split a large file; update as one article (may fail on Zhihu)",
)
@click.option(
    "--keep-extra",
    is_flag=True,
    help="Keep tail articles when the new split has fewer parts than before",
)
@click.option(
    "-y", "--yes", is_flag=True, help="Do not ask before deleting surplus tail articles"
)
def update_md(
    file: Path,
    article_ids: tuple[str, ...],
    topics: tuple[str, ...],
    no_split: bool,
    keep_extra: bool,
    yes: bool,
):
    """Update an existing article from a markdown file, keeping its ID (原地更新文章)."""
    published = _load_published()
    key, state = _find_record(published, file)
    existing = list(article_ids) or _part_ids(state)
    if not existing:
        print_error(
            "找不到已发布记录 - 用 [bold]--article-id[/bold] 指定原文章 ID"
            f"（当前标题：{file.stem}）"
        )
        sys.exit(1)
    if key != str(file):
        print_info(f"复用同名记录：{key}（{len(existing)} 篇）")
    else:
        print_info(f"复用已记录的文章：{len(existing)} 篇")
    try:
        with _get_client() as client:
            title, results, deleted, created = update_markdown(
                client,
                file,
                existing,
                list(topics),
                no_split=no_split,
                prune_extra=not keep_extra,
                assume_yes=yes,
            )
        published = _load_published()
        published[str(file)] = _record(title, results, _file_hash(file))
        if key != str(file):
            published.pop(key, None)
        _save_published(published)
        summary = f"更新 {len(results)} 篇"
        if created:
            summary += f"，新增 {created} 篇"
        if deleted:
            summary += f"，删除 {len(deleted)} 篇"
        if len(results) == 1:
            print_success(
                f"{summary}  {results[0][0]}\n"
                f"  ID: [bold]{results[0][1]}[/bold]\n"
                f"  https://zhuanlan.zhihu.com/p/{results[0][1]}"
            )
        else:
            print_success(f"{summary} of [bold]{title}[/bold]")
            _print_part_urls(results, success=True)
        for article_id in deleted:
            print_hint(f"  已删除多余文章 {article_id}")
    except click.Abort:
        print_hint("已取消，未改动任何文章")
        sys.exit(1)
    except Exception as e:
        print_error(f"Failed to update article: {e}")
        sys.exit(1)
