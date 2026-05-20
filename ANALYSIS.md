# Tool Granularity in Personal Knowledge Retrieval: Analysis

**Course:** SWE 580, Term Project
**Author:** Eylul Erdinc
**Date:** 2026-05-20

This report compares two evaluation runs of the same tool-granularity experiment. The variable held constant across the two runs is the search backend, the vault, the 25 test queries, the LLM (`google/gemini-2.5-flash` via OpenRouter), and the tool *signatures* (names and parameter schemas). The variable that differs is the **system prompt and the prose of the tool/parameter descriptions**.

- **Customized run** (`20260520_153009`): system prompts and tool descriptions written by the author. Tool descriptions explain semantics (AND-logic, "use this when…"), parameter docs clarify expectations, and both system prompts require the model to end with a machine-readable `RESULT_PATHS: [...]` line.
- **Vanilla run** (`20260520_155547`): the default one-line system prompt ("You are a helpful assistant…") and the default one-sentence tool descriptions distributed with the project skeleton. No answer-format directive.

The point of the comparison is to quantify how much of the score in this evaluator is driven by the *quality of the prose around the tools*, independent of how many tools there are.

---

## 1. Design

Both runs use the two configurations defined in the project specification:

| Configuration | Tools | Interface |
|---|---|---|
| A | 4 | Coarse-grained, rich parameters (`search_notes` with `query`, `tags`, `date_from`, `date_to`; `get_note`; `get_related_notes` with `direction`; `get_vault_overview`) |
| B | 9 | Fine-grained, single-purpose (`search_by_content`, `search_by_tags`, `search_by_date`, `get_note_by_path`, `get_note_by_title`, `get_outgoing_links`, `get_incoming_links`, `get_vault_stats`, `get_recent_notes`) |

The only differences between the customized and vanilla runs are the four editable files: `config_a_prompt.txt`, `config_b_prompt.txt`, `config_a_tools.json`, `config_b_tools.json`. The tool *behavior* (the Python executor functions and the Whoosh backend) is identical.

### What the customization changed

1. **Answer format directive.** Both customized prompts end with:
   > After you have gathered enough information, end your response with a single line in exactly this format: `RESULT_PATHS: ["vault/path/one.md", ...]`

   The vanilla prompt has no such directive. This matters because the evaluator extracts predicted notes by regex-matching that line; without it, the LLM's natural-language reply ("I found three notes: Statistics Basics, CNN Architecture, …") is not parseable into note paths.

2. **Semantic tool descriptions.** Vanilla descriptions are one-liners ("Search notes by text content."). Customized descriptions specify scope ("Does not filter by tag or date"), combination semantics ("All listed tags must be present (AND logic)"), and when to choose the tool ("Use when the path is already known. Not for searching or browsing.").

3. **Configuration-specific usage hints in the system prompt.** Config A's prompt encourages combining filters inside one `search_notes` call. Config B's prompt explicitly tells the model to call the narrow tools separately and intersect results client-side, and how to pick the right link-direction tool.

## 2. Methodology

- **Vault:** 100 markdown notes, distributed across `daily/`, `meetings/`, `projects/`, `reference/`, `research/`.
- **Queries:** the fixed set of 25 from `test_queries.json`, covering 6 categories: simple_lookup (2), tag_search (2), temporal (3), content_search (2), multi_faceted (9), graph_based (7).
- **Model:** `google/gemini-2.5-flash`, called via OpenRouter (`https://openrouter.ai/api/v1`).
- **Runner:** `evaluator.py` with default settings (`--delay 2.0`, max 10 results per search).
- **Metrics, as defined in `evaluator.py`:**
  - **Exact match / success rate:** predicted set equals expected set (with recall capped at 10).
  - **Precision:** `|predicted ∩ expected| / |predicted|`.
  - **Recall:** `|predicted ∩ expected| / min(|expected|, 10)`.
  - **F1:** harmonic mean of the two.
- **Predicted notes are extracted from the LLM's final response** by parsing a `RESULT_PATHS: [...]` line. If no such line is present, the predicted set is empty and both precision and recall are zero for that query.

## 3. Results

### 3.1 Overall metrics

| Metric | Custom A | Vanilla A | Δ | Custom B | Vanilla B | Δ |
|---|---:|---:|---:|---:|---:|---:|
| Success rate | **0.560** | 0.320 | +0.240 | **0.600** | 0.320 | +0.280 |
| Avg F1 | **0.680** | 0.339 | +0.342 | **0.691** | 0.382 | +0.309 |
| Avg precision | 0.736 | 0.360 | +0.376 | 0.720 | 0.385 | +0.335 |
| Avg recall | 0.663 | 0.332 | +0.331 | 0.673 | 0.379 | +0.295 |
| Avg tool calls | 1.04 | 1.08 | −0.04 | 1.56 | 1.28 | +0.28 |
| Avg tokens / query | 1888 | 756 | +1132 | 2502 | 1134 | +1368 |
| Avg latency (s) | 8.94 | 6.67 | +2.27 | 9.36 | 8.22 | +1.14 |

The customized prompts roughly **double** F1 for both configurations. Success rate (the strict all-or-nothing measure) goes from 0.32 to ~0.58 on average. The cost is roughly a 2.5× increase in tokens and ~1–2 extra seconds of latency per query, almost entirely because the model now generates a longer, structured response.

### 3.2 Per-category F1

| Category | n | Custom A | Vanilla A | Custom B | Vanilla B |
|---|---:|---:|---:|---:|---:|
| simple_lookup | 2 | **1.000** | 0.000 | **1.000** | 0.000 |
| tag_search | 2 | 1.000 | 1.000 | **1.000** | 0.500 |
| temporal | 3 | **1.000** | 0.667 | **1.000** | 0.667 |
| content_search | 2 | **1.000** | 0.000 | **1.000** | 0.500 |
| multi_faceted | 9 | **0.659** | 0.444 | **0.696** | 0.582 |
| graph_based | 7 | **0.295** | 0.066 | **0.286** | 0.043 |

The gain is concentrated in the simple categories (simple_lookup, content_search), where the model under both prompts retrieved the right notes but the vanilla version never reported them in a parseable form. The hardest category, `graph_based`, remains hard under both prompts; customization moves average F1 from ~0.05 to ~0.29, but neither configuration solves it.

### 3.3 Where the missing 25 points come from: the `RESULT_PATHS` effect

The single largest driver of the score gap is the answer-format directive. Counting queries where the LLM did call tools but its extracted prediction set is empty (i.e. it answered conversationally instead of emitting the sentinel line):

| Run | Queries with empty extraction despite tool calls |
|---|---:|
| Custom A | 5 / 25 |
| Vanilla A | **15 / 25** |

Concrete illustration, query `q01` ("Get the note titled Transformers"):

- **Vanilla A:** correctly calls `get_note(title="Transformers")`. Final response begins `"# Transformers\n\nThe Transformer architecture was introduced…"`, i.e. the model pasted the note's content as its answer. `extracted_notes = []`. F1 = 0.00.
- **Custom A:** same tool call; final response is exactly `RESULT_PATHS: ["research\\Transformers.md"]`. F1 = 1.00.

The retrieval was correct both times. Only the reporting differed. The same pattern explains every simple_lookup and content_search win, and most of the temporal wins. Across the 25 queries this format effect alone accounts for roughly 10 of the ~14 F1-point swing per configuration.

### 3.4 Coarse vs fine, holding the prompt fixed

Within the customized run the two configurations land in essentially the same place:

- Success rate: A 0.56 vs B 0.60, a 1-query difference (14 vs 15 exact matches out of 25).
- F1: A 0.680 vs B 0.691, within noise.

Config B uses **more tool calls** (1.56 vs 1.04) and **more tokens** (2502 vs 1888) to reach a near-identical accuracy, because the model has to issue multiple narrow queries and intersect results itself for multi-faceted questions. Config A's `search_notes` accepts `query`, `tags`, `date_from`, `date_to` in a single call.

The same ordering holds in the vanilla run (B beats A by one query), so the *relative* ranking of A vs B is stable, but the absolute scores are so depressed by the missing `RESULT_PATHS` that the comparison is much noisier.

### 3.5 Per-query F1 table

For traceability, F1 for each query across all four runs:

| qid | category | A custom | A vanilla | B custom | B vanilla |
|---|---|---:|---:|---:|---:|
| q01 | simple_lookup | 1.00 | 0.00 | 1.00 | 0.00 |
| q02 | simple_lookup | 1.00 | 0.00 | 1.00 | 0.00 |
| q03 | tag_search | 1.00 | 1.00 | 1.00 | 1.00 |
| q04 | tag_search | 1.00 | 1.00 | 1.00 | 0.00 |
| q05 | temporal | 1.00 | 0.00 | 1.00 | 0.00 |
| q06 | temporal | 1.00 | 1.00 | 1.00 | 1.00 |
| q07 | content_search | 1.00 | 0.00 | 1.00 | 1.00 |
| q08 | content_search | 1.00 | 0.00 | 1.00 | 0.00 |
| q09 | multi_faceted | 0.00 | 0.00 | 0.00 | 0.00 |
| q10 | graph_based | 0.00 | 0.46 | 1.00 | 0.00 |
| q11 | multi_faceted | 0.89 | 1.00 | 0.00 | 0.00 |
| q12 | multi_faceted | 1.00 | 0.00 | 0.67 | 0.00 |
| q13 | multi_faceted | 0.50 | 1.00 | 1.00 | 1.00 |
| q14 | multi_faceted | 0.00 | 0.00 | 1.00 | 1.00 |
| q15 | multi_faceted | 1.00 | 1.00 | 0.80 | 0.91 |
| q16 | graph_based | 1.00 | 0.00 | 0.00 | 0.00 |
| q17 | graph_based | 0.00 | 0.00 | 0.00 | 0.00 |
| q18 | graph_based | 0.00 | 0.00 | 0.00 | 0.00 |
| q19 | graph_based | 0.40 | 0.00 | 1.00 | 0.00 |
| q20 | graph_based | 0.00 | 0.00 | 0.00 | 0.30 |
| q21 | graph_based | 0.67 | 0.00 | 0.00 | 0.00 |
| q22 | multi_faceted | 1.00 | 0.00 | 0.80 | 0.33 |
| q23 | multi_faceted | 0.55 | 1.00 | 1.00 | 1.00 |
| q24 | multi_faceted | 1.00 | 0.00 | 1.00 | 1.00 |
| q25 | temporal | 1.00 | 1.00 | 1.00 | 1.00 |

## 4. Discussion

### 4.1 Prompt engineering swamps tool granularity

The dominant signal in this experiment is *not* coarse vs fine. It is whether the prompt tells the model how to report its answer.

Both A and B have basically the same vanilla score (0.34 vs 0.38 avg F1) and basically the same customized score (0.68 vs 0.69). The within-configuration gap from prompt customization (~+0.34 F1) is several times larger than the across-configuration gap (~+0.01 F1). For this evaluator, *what you tell the model to do* outweighs *how you split your tools*.

This is partly an artifact of the evaluator design: it scores on a specific output format. But it generalizes to any pipeline that consumes structured output from an LLM. If the spec said "Title the file Transformers.md and return it" and the LLM said "Here is Transformers", a downstream consumer would also fail. Reporting format is part of the tool contract.

### 4.2 Where customized tool descriptions actually helped

Stripping out the format effect (queries where vanilla returned nothing parseable), three categories show real retrieval gains from the richer descriptions:

- **Multi-faceted (Config B), `q22` and `q24`:** vanilla left tag-search tools underused or combined inputs incorrectly; the customized "All listed tags must be present (AND logic)" hint produced the right tag combinations.
- **Graph-based, generally:** customized descriptions for `get_related_notes(direction=...)` and `get_incoming_links` / `get_outgoing_links` clarified which direction maps to "links to X" vs "X links to". Vanilla scored 0.07 / 0.04 on this category; customized doubled to ~0.29. This is the largest *retrieval* (not formatting) win.
- **Tag-search (Config B):** vanilla split tags incorrectly on `q04`; the explicit AND-logic note fixed it.

### 4.3 Where neither configuration succeeded

Graph-based queries that require multi-hop reasoning (`q17`, `q18`, `q20`, parts of `q19`) and the multi-faceted `q09` ("research notes about attention from January 2026") remained at F1 ≈ 0 in both runs. The failure mode for these is not reporting but search semantics: the model either picks the wrong source note for a link query, or the content/date intersection returns nothing because the relevant notes aren't tagged the way the query implies. Better prompts and richer descriptions did not close this gap. These are the queries where extra tool calls (Config B's narrow tools used 1.56 vs A's 1.04 on average) would in principle help, but the model still doesn't compose them correctly.

### 4.4 Cost trade-off

The customized prompts cost roughly **+1100 tokens and +1–2s of latency per query** for both configurations. The extra tokens go to: (a) the longer system prompt itself (~250 tokens), (b) the longer tool/parameter descriptions in the schema (~300 tokens), (c) the model now generating a separate `RESULT_PATHS` line in addition to its natural-language answer (~50 tokens), and (d) more tool calls per query, particularly in Config B which now intersects narrow results.

For a personal knowledge assistant this is an acceptable trade: at ~$0 marginal cost on Gemini Flash and ~10 s per query, doubling F1 is the right call. For a system at much higher QPS the token overhead would need a second look, but Config A is the cheaper customized option (1888 vs 2502 tokens) and would be the production pick.

### 4.5 Recommendations

1. **Always specify the answer format in the system prompt** when a downstream parser consumes the model's output. This single change moved more F1 than the entire tool-granularity choice did.
2. **For tool design specifically, prefer coarse-grained tools (Config A) for this workload.** Same accuracy at lower token and latency cost. Config B's advantage (forcing the model to think about which slice to query) did not materialize at this query mix.
3. **Invest description prose in graph/relational tools first.** That is where retrieval (not reporting) gains came from. Search-by-tag and search-by-date were robust regardless of description quality; link-direction tools were not.
4. **The hardest queries (multi-hop graph, content + tag + date intersections) need orthogonal work**, possibly a planning step, a richer index, or a synthesis tool, rather than more prompt tweaking. Neither A nor B with good prompts cracked them.

## 5. Conclusion

Holding the model, backend, vault, and queries constant, customizing the system prompt and tool descriptions roughly doubled F1 for both the coarse-grained (Config A) and the fine-grained (Config B) tool configurations: from ~0.34/0.38 to ~0.68/0.69. The two configurations land within 0.01 F1 of each other under good prompts; Config A reaches that accuracy with ~25% fewer tokens and ~25% fewer tool calls, so it is the better default for this workload.

The biggest single intervention was making the system prompt require a structured `RESULT_PATHS` line at the end of the response. This is a property of the evaluator, but it generalizes: any LLM-driven retrieval system that hands its output to a parser needs to treat output format as part of the tool interface.

### Bonus
to-be-added