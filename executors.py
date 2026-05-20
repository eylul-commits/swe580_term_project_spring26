"""
Tool executors for Config A and Config B.
Infrastructure file. Students do not modify this.

Each executor maps tool_name to a search_backend call.
"""

from search_backend import (
    search_combined,
    search_content,
    get_note_by_path,
    get_note_by_title,
    get_outgoing_links,
    get_incoming_links,
    get_vault_stats,
    get_recent_notes,
    search_by_tags,
    search_by_date,
    create_note_file,
    add_tags_to_note_file,
    add_link_to_note_file,
)


def create_executor_a(ix, vault_path: str = "vault"):
    """Executor for Config A (coarse-grained tools)."""

    def executor(tool_name: str, args: dict):
        if tool_name == "search_notes":
            return search_combined(
                ix,
                query_str=args.get("query"),
                tags=args.get("tags"),
                date_from=args.get("date_from"),
                date_to=args.get("date_to"),
            )

        elif tool_name == "get_note":
            if args.get("path"):
                result = get_note_by_path(ix, args["path"])
            elif args.get("title"):
                result = get_note_by_title(ix, args["title"])
            else:
                return {"error": "Provide either 'path' or 'title'."}
            return result or {"error": "Note not found."}

        elif tool_name == "get_related_notes":
            direction = args.get("direction", "both")
            path = args.get("path")
            title = args.get("title")

            if not path and title:
                note = get_note_by_title(ix, title)
                path = note["path"] if note else None

            if not path:
                return {"error": "Note not found."}

            result = {}
            note_title = path.split("/")[-1].replace(".md", "").replace("_", " ")

            if direction in ("outgoing", "both"):
                result["outgoing"] = get_outgoing_links(ix, path)
            if direction in ("incoming", "both"):
                result["incoming"] = get_incoming_links(ix, note_title)

            return result

        elif tool_name == "get_vault_overview":
            stats = get_vault_stats(ix)
            recent = get_recent_notes(ix, limit=5)
            return {"stats": stats, "recent_notes": recent}

        elif tool_name == "create_note":
            if not args.get("path"):
                return {"error": "Parameter 'path' is required."}
            return create_note_file(
                ix,
                vault_path,
                rel_path=args["path"],
                title=args.get("title"),
                content=args.get("content", ""),
                tags=args.get("tags"),
                links=args.get("links"),
            )

        else:
            return {"error": f"Unknown tool: {tool_name}"}

    return executor


def create_executor_b(ix, vault_path: str = "vault"):
    """Executor for Config B (fine-grained tools)."""

    def executor(tool_name: str, args: dict):
        if tool_name == "search_by_content":
            return search_content(ix, args["query"])

        elif tool_name == "search_by_tags":
            return search_by_tags(ix, args["tags"])

        elif tool_name == "search_by_date":
            return search_by_date(ix, args.get("date_from"), args.get("date_to"))

        elif tool_name == "get_note_by_path":
            result = get_note_by_path(ix, args["path"])
            return result or {"error": "Note not found."}

        elif tool_name == "get_note_by_title":
            result = get_note_by_title(ix, args["title"])
            return result or {"error": "Note not found."}

        elif tool_name == "get_outgoing_links":
            return get_outgoing_links(ix, args["path"])

        elif tool_name == "get_incoming_links":
            return get_incoming_links(ix, args["title"])

        elif tool_name == "get_vault_stats":
            return get_vault_stats(ix)

        elif tool_name == "get_recent_notes":
            return get_recent_notes(ix, limit=args.get("limit", 10))

        elif tool_name == "create_note":
            if not args.get("path"):
                return {"error": "Parameter 'path' is required."}
            return create_note_file(
                ix,
                vault_path,
                rel_path=args["path"],
                title=args.get("title"),
                content=args.get("content", ""),
            )

        elif tool_name == "add_tags_to_note":
            if not args.get("path") or not args.get("tags"):
                return {"error": "Parameters 'path' and 'tags' are required."}
            return add_tags_to_note_file(ix, vault_path, args["path"], args["tags"])

        elif tool_name == "add_link_to_note":
            if not args.get("path") or not args.get("target_title"):
                return {"error": "Parameters 'path' and 'target_title' are required."}
            return add_link_to_note_file(ix, vault_path, args["path"], args["target_title"])

        else:
            return {"error": f"Unknown tool: {tool_name}"}

    return executor
