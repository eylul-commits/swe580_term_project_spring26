"""
Whoosh-based search backend for the personal knowledge vault.
Indexes markdown notes and provides search functions used by both Config A and Config B tools.
"""

import os
import re
import yaml
from datetime import datetime, timedelta
from pathlib import Path

from whoosh import index
from whoosh.fields import Schema, TEXT, ID, KEYWORD, DATETIME
from whoosh.qparser import QueryParser, MultifieldParser
from whoosh.query import And, Or, Term, DateRange, Every
from whoosh.analysis import StemmingAnalyzer


DEFAULT_LIMIT = 10


# ── Schema ──────────────────────────────────────────────────────────────────

SCHEMA = Schema(
    path=ID(stored=True, unique=True),
    title=TEXT(stored=True, field_boost=2.0),
    content=TEXT(analyzer=StemmingAnalyzer(), stored=True),
    tags=KEYWORD(stored=True, commas=True, lowercase=True),
    created=DATETIME(stored=True),
    modified=DATETIME(stored=True),
    links=KEYWORD(stored=True, commas=True),
    folder=ID(stored=True),
)


# ── Parsing ─────────────────────────────────────────────────────────────────

def parse_note(filepath: str, vault_root: str) -> dict | None:
    """Parse a markdown note into fields for indexing."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            raw = f.read()
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
        return None

    # Extract YAML frontmatter
    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", raw, re.DOTALL)
    if fm_match:
        try:
            frontmatter = yaml.safe_load(fm_match.group(1)) or {}
        except yaml.YAMLError:
            frontmatter = {}
        body = raw[fm_match.end():]
    else:
        frontmatter = {}
        body = raw

    # Relative path from vault root
    rel_path = os.path.relpath(filepath, vault_root)

    # Title from filename
    title = Path(filepath).stem.replace("_", " ")

    # Tags
    tags = frontmatter.get("tags", [])
    if tags is None:
        tags = []
    tags_str = ",".join(str(t).lower() for t in tags)

    # Dates
    created = frontmatter.get("created")
    modified = frontmatter.get("modified")
    if isinstance(created, str):
        created = datetime.fromisoformat(created)
    if isinstance(modified, str):
        modified = datetime.fromisoformat(modified)

    # Wiki-style links
    links = re.findall(r"\[\[([^\]]+)\]\]", body)
    links_str = ",".join(links)

    # Folder
    folder = rel_path.split(os.sep)[0] if os.sep in rel_path else ""

    return {
        "path": rel_path,
        "title": title,
        "content": body,
        "tags": tags_str,
        "created": created,
        "modified": modified,
        "links": links_str,
        "folder": folder,
    }


# ── Indexing ────────────────────────────────────────────────────────────────

def build_index(vault_path: str, index_dir: str = None) -> index.Index:
    """Build a Whoosh index from all markdown notes in the vault."""
    if index_dir is None:
        index_dir = os.path.join(vault_path, ".whoosh_index")

    os.makedirs(index_dir, exist_ok=True)
    ix = index.create_in(index_dir, SCHEMA)
    writer = ix.writer()

    count = 0
    for root, dirs, files in os.walk(vault_path):
        # Skip the index directory
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fname in files:
            if fname.endswith(".md"):
                filepath = os.path.join(root, fname)
                doc = parse_note(filepath, vault_path)
                if doc:
                    writer.add_document(**doc)
                    count += 1

    writer.commit()
    print(f"Indexed {count} notes into {index_dir}")
    return ix


def open_index(vault_path: str, index_dir: str = None) -> index.Index:
    """Open an existing Whoosh index, or build one if it doesn't exist."""
    if index_dir is None:
        index_dir = os.path.join(vault_path, ".whoosh_index")
    if index.exists_in(index_dir):
        return index.open_dir(index_dir)
    return build_index(vault_path, index_dir)


# ── Query Functions ─────────────────────────────────────────────────────────
# These are the primitives that both Config A and Config B tools call.

def _hit_to_dict(hit) -> dict:
    """Convert a Whoosh hit to a serializable dict."""
    return {
        "path": hit["path"],
        "title": hit["title"],
        "tags": hit.get("tags", ""),
        "created": hit["created"].isoformat() if hit.get("created") else None,
        "modified": hit["modified"].isoformat() if hit.get("modified") else None,
        "folder": hit.get("folder", ""),
    }


def search_content(ix: index.Index, query_str: str, limit: int = DEFAULT_LIMIT) -> list[dict]:
    """Full-text search over note content."""
    with ix.searcher() as s:
        qp = MultifieldParser(["content", "title"], ix.schema)
        q = qp.parse(query_str)
        results = s.search(q, limit=limit)
        return [_hit_to_dict(r) for r in results]


def search_by_tags(ix: index.Index, tags: list[str], limit: int = DEFAULT_LIMIT) -> list[dict]:
    """Find notes matching ALL given tags (AND logic)."""
    with ix.searcher() as s:
        tag_queries = [Term("tags", t.lower()) for t in tags]
        q = And(tag_queries) if len(tag_queries) > 1 else tag_queries[0]
        results = s.search(q, limit=limit)
        return [_hit_to_dict(r) for r in results]


def search_by_date(
    ix: index.Index,
    date_from: str = None,
    date_to: str = None,
    limit: int = DEFAULT_LIMIT,
) -> list[dict]:
    """Find notes by creation date range."""
    start = datetime.fromisoformat(date_from) if date_from else datetime(2000, 1, 1)
    end = datetime.fromisoformat(date_to) if date_to else datetime(2099, 12, 31)

    # For single-day queries, expand to full 24-hour range
    if date_from and date_to and date_from == date_to:
        end = end + timedelta(days=1) - timedelta(seconds=1)
    elif date_to and "T" not in date_to:
        end = end.replace(hour=23, minute=59, second=59)

    with ix.searcher() as s:
        q = DateRange("created", start, end)
        results = s.search(q, limit=limit)
        return [_hit_to_dict(r) for r in results]


def search_combined(
    ix: index.Index,
    query_str: str = None,
    tags: list[str] = None,
    date_from: str = None,
    date_to: str = None,
    limit: int = DEFAULT_LIMIT,
) -> list[dict]:
    """Combined search: content AND/OR tags AND/OR date range."""
    parts = []

    if query_str:
        qp = MultifieldParser(["content", "title"], ix.schema)
        parts.append(qp.parse(query_str))

    if tags:
        tag_queries = [Term("tags", t.lower()) for t in tags]
        parts.append(And(tag_queries) if len(tag_queries) > 1 else tag_queries[0])

    if date_from or date_to:
        start = datetime.fromisoformat(date_from) if date_from else datetime(2000, 1, 1)
        end = datetime.fromisoformat(date_to) if date_to else datetime(2099, 12, 31)
        if date_from and date_to and date_from == date_to:
            end = end + timedelta(days=1) - timedelta(seconds=1)
        elif date_to and "T" not in date_to:
            end = end.replace(hour=23, minute=59, second=59)
        parts.append(DateRange("created", start, end))

    if not parts:
        return []

    q = And(parts) if len(parts) > 1 else parts[0]

    with ix.searcher() as s:
        results = s.search(q, limit=limit)
        return [_hit_to_dict(r) for r in results]


def get_note_by_path(ix: index.Index, path: str) -> dict | None:
    """Retrieve a specific note by its exact path."""
    with ix.searcher() as s:
        qp = QueryParser("path", ix.schema)
        q = qp.parse(path)
        results = s.search(q, limit=1)
        if results:
            hit = results[0]
            result = _hit_to_dict(hit)
            result["content"] = hit["content"]
            result["links"] = hit.get("links", "")
            return result
    return None


def get_note_by_title(ix: index.Index, title: str) -> dict | None:
    """Retrieve a specific note by title (filename without .md)."""
    with ix.searcher() as s:
        qp = QueryParser("title", ix.schema)
        q = qp.parse(title)
        results = s.search(q, limit=1)
        if results:
            hit = results[0]
            result = _hit_to_dict(hit)
            result["content"] = hit["content"]
            result["links"] = hit.get("links", "")
            return result
    return None


def get_outgoing_links(ix: index.Index, note_path: str) -> list[dict]:
    """Get notes that the given note links TO (outgoing [[links]])."""
    note = get_note_by_path(ix, note_path)
    if not note or not note.get("links"):
        return []

    link_targets = [l.strip() for l in note["links"].split(",") if l.strip()]
    results = []
    for target in link_targets:
        linked = get_note_by_title(ix, target.replace("_", " "))
        if linked:
            results.append({k: v for k, v in linked.items() if k != "content"})
    return results


def get_incoming_links(ix: index.Index, note_title: str) -> list[dict]:
    """Get notes that link TO the given note (backlinks)."""
    # Normalize title for matching
    search_title = note_title.replace(" ", "_")
    with ix.searcher() as s:
        q = Term("links", search_title)
        results = s.search(q, limit=DEFAULT_LIMIT)
        return [_hit_to_dict(r) for r in results]


def get_vault_stats(ix: index.Index) -> dict:
    """Get overall vault statistics."""
    with ix.searcher() as s:
        total = s.doc_count()
        # Count by folder
        folders = {}
        all_tags = set()
        for docnum in range(s.doc_count()):
            doc = s.stored_fields(docnum)
            folder = doc.get("folder", "unknown")
            folders[folder] = folders.get(folder, 0) + 1
            if doc.get("tags"):
                for t in doc["tags"].split(","):
                    if t.strip():
                        all_tags.add(t.strip())

    return {
        "total_notes": total,
        "folders": folders,
        "total_tags": len(all_tags),
        "tags": sorted(all_tags),
    }


def get_recent_notes(ix: index.Index, limit: int = DEFAULT_LIMIT) -> list[dict]:
    """Get the most recently modified notes."""
    with ix.searcher() as s:
        results = s.search(Every(), sortedby="modified", reverse=True, limit=limit)
        return [_hit_to_dict(r) for r in results]


# ── Note Creation / Mutation ────────────────────────────────────────────────
# These functions write to the vault and keep the Whoosh index in sync.

def _reindex_note(ix: index.Index, vault_path: str, full_path: str) -> dict | None:
    doc = parse_note(full_path, vault_path)
    if not doc:
        return None
    writer = ix.writer()
    writer.update_document(**doc)
    writer.commit()
    return doc


def create_note_file(
    ix: index.Index,
    vault_path: str,
    rel_path: str,
    title: str = None,
    content: str = "",
    tags: list[str] = None,
    links: list[str] = None,
) -> dict:
    """Create a markdown note with YAML frontmatter and index it."""
    if not rel_path.endswith(".md"):
        rel_path = rel_path + ".md"

    full_path = os.path.join(vault_path, rel_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    now_iso = datetime.now().replace(microsecond=0).isoformat()
    fm = {
        "title": title or Path(rel_path).stem.replace("_", " "),
        "tags": list(tags) if tags else [],
        "created": now_iso,
        "modified": now_iso,
    }
    fm_yaml = yaml.safe_dump(fm, sort_keys=False).strip()

    body_parts = []
    if content:
        body_parts.append(content.rstrip())
    if links:
        link_line = " ".join(f"[[{l.replace(' ', '_')}]]" for l in links)
        body_parts.append(link_line)

    body = "\n\n".join(body_parts)
    full_text = f"---\n{fm_yaml}\n---\n{body}\n"

    with open(full_path, "w", encoding="utf-8") as f:
        f.write(full_text)

    _reindex_note(ix, vault_path, full_path)
    return {"path": rel_path, "created": True}


def add_tags_to_note_file(
    ix: index.Index,
    vault_path: str,
    rel_path: str,
    tags: list[str],
) -> dict:
    """Append tags to an existing note's YAML frontmatter, deduplicated."""
    full_path = os.path.join(vault_path, rel_path)
    if not os.path.exists(full_path):
        return {"error": f"Note not found: {rel_path}"}

    with open(full_path, "r", encoding="utf-8") as f:
        raw = f.read()

    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", raw, re.DOTALL)
    if fm_match:
        try:
            fm = yaml.safe_load(fm_match.group(1)) or {}
        except yaml.YAMLError:
            fm = {}
        body = raw[fm_match.end():]
    else:
        fm = {}
        body = raw

    existing = list(fm.get("tags") or [])
    merged = list(dict.fromkeys([*existing, *tags]))
    fm["tags"] = merged
    fm["modified"] = datetime.now().replace(microsecond=0).isoformat()

    fm_yaml = yaml.safe_dump(fm, sort_keys=False).strip()
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(f"---\n{fm_yaml}\n---\n{body}")

    _reindex_note(ix, vault_path, full_path)
    return {"path": rel_path, "tags": merged}


def add_link_to_note_file(
    ix: index.Index,
    vault_path: str,
    rel_path: str,
    target_title: str,
) -> dict:
    """Append a wiki-style [[link]] to the body of an existing note."""
    full_path = os.path.join(vault_path, rel_path)
    if not os.path.exists(full_path):
        return {"error": f"Note not found: {rel_path}"}

    with open(full_path, "r", encoding="utf-8") as f:
        raw = f.read()

    link_token = f"[[{target_title.replace(' ', '_')}]]"
    if link_token in raw:
        _reindex_note(ix, vault_path, full_path)
        return {"path": rel_path, "added_link": target_title, "already_present": True}

    new_raw = raw.rstrip() + f"\n\n{link_token}\n"
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(new_raw)

    _reindex_note(ix, vault_path, full_path)
    return {"path": rel_path, "added_link": target_title}


# ── Main (for testing) ──────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    vault_path = sys.argv[1] if len(sys.argv) > 1 else "vault"
    ix = build_index(vault_path)

    print("\n--- Vault Stats ---")
    stats = get_vault_stats(ix)
    print(f"Total notes: {stats['total_notes']}")
    print(f"Folders: {stats['folders']}")
    print(f"Tags ({stats['total_tags']}): {stats['tags']}")

    print("\n--- Content Search: 'attention' ---")
    for r in search_content(ix, "attention"):
        print(f"  {r['path']} (tags: {r['tags']})")

    print("\n--- Tag Search: ['project'] ---")
    for r in search_by_tags(ix, ["project"]):
        print(f"  {r['path']}")

    print("\n--- Incoming Links: 'Transformers' ---")
    for r in get_incoming_links(ix, "Transformers"):
        print(f"  {r['path']}")
