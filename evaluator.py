"""
Evaluation Harness
Runs all test queries through both configurations, parses results, and computes metrics.

Usage:
    python evaluator.py --api-key YOUR_KEY [--base-url URL] [--model MODEL]

Environment variable alternative:
    export LLM_API_KEY=your-key
    python evaluator.py
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime

import yaml

from search_backend import build_index, open_index
from llm_runner import LLMRunner
from executors import create_executor_a, create_executor_b


# ── Response Parser ─────────────────────────────────────────────────────────

def extract_note_paths(response: str) -> list[str]:
    """
    Extract note paths from the LLM's response.
    Looks for RESULT_PATHS line first, then falls back to regex extraction.
    Any mix of '/' and '\\' separators is collapsed to '/' so Windows-style
    paths returned by the backend match the forward-slash paths in test_queries.json.
    """
    def _norm(p: str) -> str:
        return re.sub(r"[\\/]+", "/", p)

    # Strategy 1: Look for the explicit RESULT_PATHS marker
    match = re.search(r"RESULT_PATHS:\s*\[([^\]]*)\]", response)
    if match:
        raw = match.group(1)
        paths = re.findall(r'"([^"]+\.md)"', raw)
        if not paths:
            paths = re.findall(r"'([^']+\.md)'", raw)
        if paths:
            return sorted({_norm(p) for p in paths})

    # Strategy 2: Extract any .md file paths from the response
    paths = re.findall(r'(?:[\w-]+[\\/]+)?[\w-]+\.md', response)
    # Deduplicate and sort
    return sorted({_norm(p) for p in paths})


# ── Metrics ─────────────────────────────────────────────────────────────────

def compute_metrics(extracted: list[str], expected: list[str]) -> dict:
    """Compute precision, recall, F1, and exact match for a single query."""
    extracted_set = set(extracted)
    expected_set = set(expected)

    if not expected_set:
        return {
            "exact_match": len(extracted_set) == 0,
            "precision": 1.0 if not extracted_set else 0.0,
            "recall": 1.0,
            "f1": 1.0 if not extracted_set else 0.0,
        }

    effective_size = min(len(expected_set), 10)

    true_positives = extracted_set & expected_set
    precision = len(true_positives) / len(extracted_set) if extracted_set else 0.0
    recall = min(len(true_positives) / effective_size, 1.0)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall > 0 else 0.0

    exact_match = (precision == 1.0 and len(true_positives) >= effective_size)

    return {
        "exact_match": exact_match,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


# ── Synthesis Ground Truth ─────────────────────────────────────────────────

def cleanup_synthesis_target(query: dict, vault_path: str) -> None:
    """Remove a synthesis query's expected output file (if present) before the run."""
    if query.get("category") != "synthesis":
        return
    target = query.get("expected_file")
    if not target:
        return
    full = os.path.join(vault_path, target)
    if os.path.exists(full):
        try:
            os.remove(full)
        except OSError:
            pass


def evaluate_synthesis_file(query: dict, vault_path: str) -> dict:
    """Check the filesystem after a synthesis query and compute metrics."""
    rel = query["expected_file"]
    full = os.path.join(vault_path, rel)

    expected_subs = query.get("expected_substrings", []) or []
    expected_links = query.get("expected_links", []) or []
    expected_tags = query.get("expected_tags", []) or []

    if not os.path.exists(full):
        return {
            "file_exists": False,
            "substring_hits": 0,
            "substring_total": len(expected_subs),
            "link_hits": 0,
            "link_total": len(expected_links),
            "tag_hits": 0,
            "tag_total": len(expected_tags),
            "exact_match": False,
            "precision": 0.0,
            "recall": 0.0,
            "f1": 0.0,
        }

    with open(full, "r", encoding="utf-8") as f:
        raw = f.read()

    lower = raw.lower()
    sub_hits = sum(1 for s in expected_subs if s.lower() in lower)

    link_hits = 0
    for link in expected_links:
        token_under = f"[[{link.replace(' ', '_')}]]"
        token_space = f"[[{link.replace('_', ' ')}]]"
        if token_under in raw or token_space in raw:
            link_hits += 1

    tag_hits = 0
    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", raw, re.DOTALL)
    if fm_match:
        try:
            fm = yaml.safe_load(fm_match.group(1)) or {}
            file_tags = [str(t).lower() for t in (fm.get("tags") or [])]
            tag_hits = sum(1 for t in expected_tags if t.lower() in file_tags)
        except yaml.YAMLError:
            pass

    sub_ok = sub_hits == len(expected_subs)
    link_ok = link_hits == len(expected_links)
    tag_ok = tag_hits == len(expected_tags)
    exact_match = sub_ok and link_ok and tag_ok

    total_expected = len(expected_subs) + len(expected_links) + len(expected_tags)
    total_hits = sub_hits + link_hits + tag_hits
    score = total_hits / total_expected if total_expected else 1.0

    return {
        "file_exists": True,
        "substring_hits": sub_hits,
        "substring_total": len(expected_subs),
        "link_hits": link_hits,
        "link_total": len(expected_links),
        "tag_hits": tag_hits,
        "tag_total": len(expected_tags),
        "exact_match": exact_match,
        "precision": round(score, 4),
        "recall": round(score, 4),
        "f1": round(score, 4),
    }


# ── Single Query Evaluation ────────────────────────────────────────────────

def evaluate_query(runner: LLMRunner, query: dict, tools: list, executor,
                   system_prompt: str = None, verbose: bool = False,
                   vault_path: str = "vault") -> dict:
    """Run a single query and evaluate the result."""
    if query.get("category") == "synthesis":
        cleanup_synthesis_target(query, vault_path)

    kwargs = dict(query=query["query"], tools=tools, tool_executor=executor, verbose=verbose)
    if system_prompt:
        kwargs["system_prompt"] = system_prompt
    result = runner.run(**kwargs)

    if query.get("category") == "synthesis":
        metrics = evaluate_synthesis_file(query, vault_path)
        extracted = []
        expected = []
    else:
        extracted = extract_note_paths(result["response"])
        expected = sorted(query.get("expected_notes", []))
        metrics = compute_metrics(extracted, expected)

    return {
        "query_id": query["id"],
        "category": query["category"],
        "query": query["query"],
        "expected_notes": expected,
        "extracted_notes": extracted,
        "response": result["response"],
        "tool_calls": result["tool_calls"],
        "trace": result.get("trace", []),
        "total_input_tokens": result["total_input_tokens"],
        "total_output_tokens": result["total_output_tokens"],
        "total_tokens": result["total_input_tokens"] + result["total_output_tokens"],
        "latency_seconds": result["latency_seconds"],
        "rounds": result["rounds"],
        "num_tool_calls": len(result["tool_calls"]),
        **metrics,
    }


# ── Full Evaluation ────────────────────────────────────────────────────────

def run_evaluation(
    runner: LLMRunner,
    queries: list[dict],
    tools: list,
    executor,
    config_name: str,
    delay: float = 2.0,
    verbose: bool = False,
    system_prompt: str = None,
    vault_path: str = "vault",
) -> dict:
    """Run all queries for a configuration and aggregate metrics."""
    results = []

    print(f"\n{'='*60}")
    print(f"Running {config_name}: {len(queries)} queries")
    print(f"{'='*60}")

    for i, query in enumerate(queries):
        print(f"\n[{i+1}/{len(queries)}] {query['id']}: {query['query'][:60]}...")

        try:
            result = evaluate_query(runner, query, tools, executor,
                                    system_prompt=system_prompt, verbose=verbose,
                                    vault_path=vault_path)
            status = "✓" if result["exact_match"] else "✗"
            print(f"  {status} exact_match={result['exact_match']} "
                  f"precision={result['precision']} recall={result['recall']} "
                  f"tools={result['num_tool_calls']} tokens={result['total_tokens']}")
            results.append(result)
        except Exception as e:
            print(f"  ✗ ERROR: {e}")
            results.append({
                "query_id": query["id"],
                "category": query["category"],
                "query": query["query"],
                "expected_notes": query.get("expected_notes", []),
                "extracted_notes": [],
                "error": str(e),
                "exact_match": False,
                "precision": 0.0,
                "recall": 0.0,
                "f1": 0.0,
                "total_tokens": 0,
                "num_tool_calls": 0,
                "latency_seconds": 0,
                "rounds": 0,
            })

        # Rate limit delay
        if i < len(queries) - 1:
            time.sleep(delay)

    # Aggregate metrics
    n = len(results)
    aggregate = {
        "config": config_name,
        "total_queries": n,
        "exact_matches": sum(1 for r in results if r["exact_match"]),
        "success_rate": round(sum(1 for r in results if r["exact_match"]) / n, 4) if n else 0,
        "avg_precision": round(sum(r["precision"] for r in results) / n, 4) if n else 0,
        "avg_recall": round(sum(r["recall"] for r in results) / n, 4) if n else 0,
        "avg_f1": round(sum(r["f1"] for r in results) / n, 4) if n else 0,
        "avg_tool_calls": round(sum(r["num_tool_calls"] for r in results) / n, 2) if n else 0,
        "avg_tokens": round(sum(r["total_tokens"] for r in results) / n, 1) if n else 0,
        "avg_latency": round(sum(r["latency_seconds"] for r in results) / n, 3) if n else 0,
        "total_tokens": sum(r["total_tokens"] for r in results),
        "by_category": {},
    }

    # Per-category breakdown
    categories = set(r["category"] for r in results)
    for cat in sorted(categories):
        cat_results = [r for r in results if r["category"] == cat]
        cn = len(cat_results)
        aggregate["by_category"][cat] = {
            "count": cn,
            "exact_matches": sum(1 for r in cat_results if r["exact_match"]),
            "success_rate": round(sum(1 for r in cat_results if r["exact_match"]) / cn, 4),
            "avg_f1": round(sum(r["f1"] for r in cat_results) / cn, 4),
            "avg_tool_calls": round(sum(r["num_tool_calls"] for r in cat_results) / cn, 2),
        }

    return {
        "aggregate": aggregate,
        "results": results,
    }


# ── Report ──────────────────────────────────────────────────────────────────

def print_comparison(eval_a: dict, eval_b: dict):
    """Print a side-by-side comparison of both configurations."""
    a = eval_a["aggregate"]
    b = eval_b["aggregate"]

    print(f"\n{'='*60}")
    print("COMPARISON: Config A (Coarse) vs Config B (Fine)")
    print(f"{'='*60}")
    print(f"{'Metric':<25} {'Config A':>12} {'Config B':>12} {'Winner':>10}")
    print(f"{'-'*60}")

    rows = [
        ("Success Rate", a["success_rate"], b["success_rate"], "higher"),
        ("Avg Precision", a["avg_precision"], b["avg_precision"], "higher"),
        ("Avg Recall", a["avg_recall"], b["avg_recall"], "higher"),
        ("Avg F1", a["avg_f1"], b["avg_f1"], "higher"),
        ("Avg Tool Calls", a["avg_tool_calls"], b["avg_tool_calls"], "lower"),
        ("Avg Tokens", a["avg_tokens"], b["avg_tokens"], "lower"),
        ("Avg Latency (s)", a["avg_latency"], b["avg_latency"], "lower"),
    ]

    for label, va, vb, better in rows:
        if better == "higher":
            winner = "A" if va > vb else ("B" if vb > va else "Tie")
        else:
            winner = "A" if va < vb else ("B" if vb < va else "Tie")
        print(f"{label:<25} {va:>12} {vb:>12} {winner:>10}")

    # Per-category comparison
    print(f"\n{'='*60}")
    print("PER-CATEGORY SUCCESS RATES")
    print(f"{'='*60}")
    print(f"{'Category':<20} {'Config A':>12} {'Config B':>12}")
    print(f"{'-'*45}")

    all_cats = sorted(set(list(a["by_category"].keys()) + list(b["by_category"].keys())))
    for cat in all_cats:
        sa = a["by_category"].get(cat, {}).get("success_rate", "N/A")
        sb = b["by_category"].get(cat, {}).get("success_rate", "N/A")
        print(f"{cat:<20} {str(sa):>12} {str(sb):>12}")


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Evaluate tool granularity configurations")
    parser.add_argument("--api-key", default=os.environ.get("LLM_API_KEY"), help="LLM API key")
    parser.add_argument("--base-url", default="https://openrouter.ai/api/v1", help="API base URL")
    parser.add_argument("--model", default="google/gemini-2.5-flash", help="Model name")
    parser.add_argument("--vault", default="vault", help="Path to vault directory")
    parser.add_argument("--queries", default="test_queries.json", help="Path to test queries JSON")
    parser.add_argument("--output-dir", default="results", help="Directory for output files")
    parser.add_argument("--delay", type=float, default=2.0, help="Delay between queries (seconds)")
    parser.add_argument("--config", choices=["a", "b", "both"], default="both", help="Which config to run")
    parser.add_argument("--verbose", action="store_true", help="Print round-by-round tool call trace during evaluation")
    args = parser.parse_args()

    if not args.api_key:
        print("ERROR: Provide --api-key or set LLM_API_KEY environment variable.")
        sys.exit(1)

    # Load queries
    with open(args.queries) as f:
        query_data = json.load(f)
    queries = query_data["queries"]
    print(f"Loaded {len(queries)} test queries")

    # Build/open index
    ix = build_index(args.vault)

    # Create runner
    runner = LLMRunner(base_url=args.base_url, api_key=args.api_key, model=args.model)
    print(f"Using model: {args.model} via {args.base_url}")

    # Output directory
    os.makedirs(args.output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    eval_a = None
    eval_b = None

    # Load tool definitions and prompts from student-editable files
    with open("config_a_tools.json") as f:
        tools_a = json.load(f)
    with open("config_b_tools.json") as f:
        tools_b = json.load(f)
    with open("config_a_prompt.txt") as f:
        prompt_a = f.read()
    with open("config_b_prompt.txt") as f:
        prompt_b = f.read()

    # Run Config A
    if args.config in ("a", "both"):
        eval_a = run_evaluation(
            runner, queries, tools_a, create_executor_a(ix, args.vault),
            config_name="Config A (Coarse-Grained)", delay=args.delay,
            verbose=args.verbose, system_prompt=prompt_a,
            vault_path=args.vault,
        )
        output_path = os.path.join(args.output_dir, f"config_a_{timestamp}.json")
        with open(output_path, "w") as f:
            json.dump(eval_a, f, indent=2, default=str)
        print(f"\nConfig A results saved to {output_path}")

    # Run Config B
    if args.config in ("b", "both"):
        eval_b = run_evaluation(
            runner, queries, tools_b, create_executor_b(ix, args.vault),
            config_name="Config B (Fine-Grained)", delay=args.delay,
            verbose=args.verbose, system_prompt=prompt_b,
            vault_path=args.vault,
        )
        output_path = os.path.join(args.output_dir, f"config_b_{timestamp}.json")
        with open(output_path, "w") as f:
            json.dump(eval_b, f, indent=2, default=str)
        print(f"\nConfig B results saved to {output_path}")

    # Comparison
    if eval_a and eval_b:
        print_comparison(eval_a, eval_b)

        # Save comparison summary
        summary_path = os.path.join(args.output_dir, f"comparison_{timestamp}.json")
        with open(summary_path, "w") as f:
            json.dump({
                "timestamp": timestamp,
                "model": args.model,
                "base_url": args.base_url,
                "num_queries": len(queries),
                "config_a": eval_a["aggregate"],
                "config_b": eval_b["aggregate"],
            }, f, indent=2)
        print(f"\nComparison saved to {summary_path}")


if __name__ == "__main__":
    main()
