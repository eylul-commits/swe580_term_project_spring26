# Tool Granularity in Personal Knowledge Retrieval: Analysis

**Course:** SWE 580, Term Project
**Author:** Eylul Erdinc
**Date:** 2026-05-20

This report compares two evaluation runs for our tool-granularity experiment. The variable held constant across the two runs is the search backend, the vault, the 25 test queries, the LLM (`google/gemini-2.5-flash` via OpenRouter), and the tool *signatures* (names and parameter schemas). The variable that differs is the **system prompt and the prose of the tool descriptions**.

- **Customized run** (`20260520_153009`): detailed system prompts and tool descriptions. Tool descriptions explain semantics ("use this when…"), parameter docs clarify expectations and both system prompts require the model to end with a `RESULT_PATHS: [...]` line.
- **Vanilla run** (`20260520_155547`): the default one-line system prompt and the default one-sentence tool descriptions distributed with the project skeleton.

---

## 1. Design

Both runs use the two configurations defined in the project specification:


| Configuration | Tools | Interface                                                                                                                                                                                                          |
| ------------- | ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| A             | 4     | Coarse-grained, rich parameters (`search_notes` with `query`, `tags`, `date_from`, `date_to`; `get_note`; `get_related_notes` with `direction`; `get_vault_overview`)                                              |
| B             | 9     | Fine-grained, single-purpose (`search_by_content`, `search_by_tags`, `search_by_date`, `get_note_by_path`, `get_note_by_title`, `get_outgoing_links`, `get_incoming_links`, `get_vault_stats`, `get_recent_notes`) |


The only differences between the customized and vanilla runs are the four editable files: `config_a_prompt.txt`, `config_b_prompt.txt`, `config_a_tools.json`, `config_b_tools.json`. The tool *behavior* is identical.

### What the customization changed

1. **Answer format directive.** Both customized prompts end with:
  > After you have gathered enough information, end your response with a single line in exactly this format: `RESULT_PATHS: ["vault/path/one.md", ...]`  
  >  The vanilla prompt has no such directive. This matters because the evaluator extracts predicted notes by regex-matching that line.
2. **Semantic tool descriptions.** Vanilla descriptions are one liners. Customized descriptions specify scope ("Does not filter by tag or date"), combination semantics ("All listed tags must be present (AND logic)"), and when to choose the tool ("Use when the path is already known. Not for searching or browsing.").
3. **Configuration specific usage hints in the system prompt.** Config A's prompt encourages combining filters inside one `search_notes` call. Config B's prompt explicitly tells the model to call the narrow tools separately and intersect results and how to pick the right link direction tool.

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


| Metric             | Custom A  | Vanilla A | Δ      | Custom B  | Vanilla B | Δ      |
| ------------------ | --------- | --------- | ------ | --------- | --------- | ------ |
| Success rate       | **0.560** | 0.320     | +0.240 | **0.600** | 0.320     | +0.280 |
| Avg F1             | **0.680** | 0.339     | +0.342 | **0.691** | 0.382     | +0.309 |
| Avg precision      | 0.736     | 0.360     | +0.376 | 0.720     | 0.385     | +0.335 |
| Avg recall         | 0.663     | 0.332     | +0.331 | 0.673     | 0.379     | +0.295 |
| Avg tool calls     | 1.04      | 1.08      | −0.04  | 1.56      | 1.28      | +0.28  |
| Avg tokens / query | 1888      | 756       | +1132  | 2502      | 1134      | +1368  |
| Avg latency (s)    | 8.94      | 6.67      | +2.27  | 9.36      | 8.22      | +1.14  |


The customized prompts roughly **double** F1 for both configurations. Success rate goes from 0.32 to ~0.58 on average. The cost is roughly a 2.5× increase in tokens and ~1-2 extra seconds of latency per query, almost entirely because the model now generates a longer response.

### 3.2 Per-category F1


| Category       | n   | Custom A  | Vanilla A | Custom B  | Vanilla B |
| -------------- | --- | --------- | --------- | --------- | --------- |
| simple_lookup  | 2   | **1.000** | 0.000     | **1.000** | 0.000     |
| tag_search     | 2   | 1.000     | 1.000     | **1.000** | 0.500     |
| temporal       | 3   | **1.000** | 0.667     | **1.000** | 0.667     |
| content_search | 2   | **1.000** | 0.000     | **1.000** | 0.500     |
| multi_faceted  | 9   | **0.659** | 0.444     | **0.696** | 0.582     |
| graph_based    | 7   | **0.295** | 0.066     | **0.286** | 0.043     |


The gain is concentrated in the simple categories (simple_lookup, content_search), where the model under both prompts retrieved the right notes but the vanilla version never reported them in a parseable form. The hardest category, `graph_based`, remains hard under both prompts. Customization moves average F1 from ~0.05 to ~0.29, but neither configuration solves it.

### 3.3 Where the missing 25 points come from: the `RESULT_PATHS` effect

The single largest driver of the score gap is the answer-format directive. Counting queries where the LLM did call tools but its extracted prediction set is empty (it answered conversationally instead of emitting the specific line):


| Run       | Queries with empty extraction despite tool calls |
| --------- | ------------------------------------------------ |
| Custom A  | 5 / 25                                           |
| Vanilla A | **15 / 25**                                      |


Concrete illustration, query `q01` ("Get the note titled Transformers"):

- **Vanilla A:** correctly calls `get_note(title="Transformers")`. Final response begins `"# Transformers\n\nThe Transformer architecture was introduced…"`, the model pasted the note's content as its answer. `extracted_notes = []`. F1 = 0.00.
- **Custom A:** same tool call, final response is exactly `RESULT_PATHS: ["research\\Transformers.md"]`. F1 = 1.00.

The retrieval was correct both times. Only the reporting differed. The same pattern explains every simple_lookup and content_search win and most of the temporal wins. Across the 25 queries this format effect alone accounts for roughly 10 of the ~14 F1 point increase per configuration.

### 3.4 Coarse vs fine, holding the prompt fixed

Within the customized run the two configurations score about the same:

- Success rate: A 0.56 vs B 0.60, a 1 query difference (14 vs 15 exact matches out of 25).
- F1: A 0.680 vs B 0.691.

Config B uses **more tool calls** (1.56 vs 1.04) and **more tokens** (2502 vs 1888) to reach a near identical accuracy. Because the model has to issue multiple narrow queries and intersect results itself for multi-faceted questions. Config A's `search_notes` accepts `query`, `tags`, `date_from`, `date_to` in a single call.

The same ordering holds in the vanilla run (B beats A by one query), so the *relative* ranking of A vs B is the same. But the absolute scores are so low because of the missing `RESULT_PATHS` that the comparison is much noisier.

### 3.5 Per-query F1 table

For traceability, F1 for each query across all four runs:


| qid | category       | A custom | A vanilla | B custom | B vanilla |
| --- | -------------- | -------- | --------- | -------- | --------- |
| q01 | simple_lookup  | 1.00     | 0.00      | 1.00     | 0.00      |
| q02 | simple_lookup  | 1.00     | 0.00      | 1.00     | 0.00      |
| q03 | tag_search     | 1.00     | 1.00      | 1.00     | 1.00      |
| q04 | tag_search     | 1.00     | 1.00      | 1.00     | 0.00      |
| q05 | temporal       | 1.00     | 0.00      | 1.00     | 0.00      |
| q06 | temporal       | 1.00     | 1.00      | 1.00     | 1.00      |
| q07 | content_search | 1.00     | 0.00      | 1.00     | 1.00      |
| q08 | content_search | 1.00     | 0.00      | 1.00     | 0.00      |
| q09 | multi_faceted  | 0.00     | 0.00      | 0.00     | 0.00      |
| q10 | graph_based    | 0.00     | 0.46      | 1.00     | 0.00      |
| q11 | multi_faceted  | 0.89     | 1.00      | 0.00     | 0.00      |
| q12 | multi_faceted  | 1.00     | 0.00      | 0.67     | 0.00      |
| q13 | multi_faceted  | 0.50     | 1.00      | 1.00     | 1.00      |
| q14 | multi_faceted  | 0.00     | 0.00      | 1.00     | 1.00      |
| q15 | multi_faceted  | 1.00     | 1.00      | 0.80     | 0.91      |
| q16 | graph_based    | 1.00     | 0.00      | 0.00     | 0.00      |
| q17 | graph_based    | 0.00     | 0.00      | 0.00     | 0.00      |
| q18 | graph_based    | 0.00     | 0.00      | 0.00     | 0.00      |
| q19 | graph_based    | 0.40     | 0.00      | 1.00     | 0.00      |
| q20 | graph_based    | 0.00     | 0.00      | 0.00     | 0.30      |
| q21 | graph_based    | 0.67     | 0.00      | 0.00     | 0.00      |
| q22 | multi_faceted  | 1.00     | 0.00      | 0.80     | 0.33      |
| q23 | multi_faceted  | 0.55     | 1.00      | 1.00     | 1.00      |
| q24 | multi_faceted  | 1.00     | 0.00      | 1.00     | 1.00      |
| q25 | temporal       | 1.00     | 1.00      | 1.00     | 1.00      |


## 4. Discussion

### 4.1 Prompt design matters more than tool granularity

The main signal in this experiment is not coarse vs fine. It is whether the prompt tells the model how to report its answer.

Both A and B have basically the same vanilla score (0.34 vs 0.38 avg F1) and basically the same customized score (0.68 vs 0.69). For this evaluator, how the model is instructed matters more than how the tools are split.

This is partly an artifact of the evaluator design, since it scores on a specific output format. But the same point applies to any system that parses structured output from an LLM.

### 4.2 Where customized tool descriptions actually helped

Stripping out the format effect, three categories show real retrieval gains from the richer descriptions:

- **Multi-faceted (Config B),** `q22` **and** `q24`**:** vanilla left tag search tools underused or combined inputs incorrectly; the customized "All listed tags must be present" hint produced the right tag combinations.
- **Graph-based, generally:** customized descriptions for `get_related_notes(direction=...)` and `get_incoming_links` / `get_outgoing_links` clarified which direction maps to "links to X" vs "X links to". Vanilla scored 0.07 / 0.04 on this category. Customized doubled to ~0.29. This is the largest *retrieval* (not formatting) win.
- **Tag-search (Config B):** vanilla split tags incorrectly on `q04`, the explicit AND-logic note fixed it.

### 4.3 Where neither configuration succeeded

Graph-based queries that require multi-hop reasoning (`q17`, `q18`, `q20`, parts of `q19`) and the multi-faceted `q09` ("research notes about attention from January 2026") remained at F1 ≈ 0 in both runs. The failure mode for these is not reporting but search semantics: the model either picks the wrong source note for a link query, or the content/date intersection returns nothing because the relevant notes aren't tagged the way the query implies. Better prompts and richer descriptions did not close this gap. These are the queries where Config B's narrow tools could in theory help, since it already makes more calls per query (1.56 vs A's 1.04) and could break a hard query into separate search and link steps. But the model still chains those steps incorrectly, so the extra calls do not improve accuracy on this hard subset.

### 4.4 Cost trade-off

The customized prompts cost roughly **+1100 tokens and +1-2s of latency per query** for both configurations. The extra tokens go to: (a) the longer system prompt itself (250 tokens), (b) the longer tool descriptions in the schema (~300 tokens), (c) the model now generating a separate `RESULT_PATHS` line in addition to its natural-language answer (50 tokens), and (d) more tool calls per query, particularly in Config B (narrow results).

For a personal knowledge assistant the trade is worth it: doubling F1 costs almost nothing on Gemini Flash and only a few seconds per query. At high request volumes the extra tokens matter more and there Config A is the better pick because it is the cheaper of the two options (1888 vs 2502 tokens).

### 4.5 Discussion

1. **Always specify the answer format in the system prompt** when a downstream parser consumes the model's output. This single change moved more F1 than the entire tool-granularity choice did.
2. **For tool design specifically, prefer coarse-grained tools (Config A) for this workload.** It reaches the same accuracy while using fewer tokens and less time. The benefit I expected from Config B did not appear on these queries. The note-creation experiment reinforces this from the write side: on synthesis queries the two configs were *identical* in correctness (1.00 vs 1.00) but the coarse interface used 5× fewer tool calls and ~4× fewer tokens.
3. **Write the most careful descriptions for the link tools first.** That is where better descriptions actually improved retrieval. Tag search and date search worked well no matter how they were described, the link direction tools did not.
4. **The hardest queries need a different approach, not more prompt tweaking.** Multi-hop graph queries and combined content + tag + date queries would need something like a planning step or a richer index. Good prompts did not solve them in either config.

## 5. Conclusion

Holding the model, backend, vault, and queries constant, customizing the system prompt and tool descriptions roughly doubled F1 for both the coarse-grained (Config A) and the fine-grained (Config B) tool configurations: from ~0.34/0.38 to ~0.68/0.69. The two configurations land within 0.01 F1 of each other under good prompts; Config A reaches that accuracy with ~25% fewer tokens and ~25% fewer tool calls, so it is the better default for this workload.

The biggest single intervention was making the system prompt require a structured `RESULT_PATHS` line at the end of the response. 

## Bonus: Note Creation Tools and Synthesis Queries

### B.1 Tool design: coarse vs fine

The note creation tools mirror the granularity of the search tools, so the same A vs B contrast applies:


|                                        | Config A (coarse)                                                                                    | Config B (fine)                                                                                                             |
| -------------------------------------- | ---------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| Creation interface                     | **One** tool, `create_note(path, title, content, tags, links)`: path, body, tags, and outgoing links | **Three** tools: `create_note(path, title, content)`, `add_tags_to_note(path, tags)`, `add_link_to_note(path,target_title)` |
| Calls to build a (tagged, 3 link) note | 1                                                                                                    | 1 + 1 + 3 = **5 (with one call per tag set and one call per link)**                                                         |
| System-prompt guidance                 | "prefer one `create_note` call that already includes the desired tags and links"                     | "call `create_note` first, then `add_tags_to_note` and `add_link_to_note` for each tag and each link"                       |


All three tools are backed by shared functions in `search_backend.py` that write the markdown file with YAML frontmatter and re-index it via `_reindex_note`. A newly created note is searchable within the same session. 

### B.2 Synthesis queries and evaluation method

Three synthesis queries (`qs01`-`qs03`) were added to `test_queries.json` under a new `synthesis` category. These are the only inputs that use the new write tools and each one also carries the ground truth (target path, tags, links):


| qid  | New note                                    | Expected tags         | Expected links                                     |
| ---- | ------------------------------------------- | --------------------- | -------------------------------------------------- |
| qs01 | `synthesis/Attention_Summary.md`            | `summary`, `nlp`      | Transformers, Self Attention, Attention Mechanisms |
| qs02 | `synthesis/Python_Toolkit.md`               | `reference`, `python` | Python Tips, Pandas Tips, Numpy Guide              |
| qs03 | `synthesis/Language_Models_Reading_List.md` | `reading-list`, `nlp` | BERT, GPT, Transformers                            |


Synthesis can't be scored by the `RESULT_PATHS` regex used for retrieval, because the "answer" is a file on disk, not a list of retrieved paths. The evaluator therefore handles the `synthesis` category separately (`evaluate_synthesis_file` in `evaluator.py`):

1. **Before** the query runs, `cleanup_synthesis_target` deletes any pre-existing target file, so each run starts clean.
2. The model is given the query and the creation tools and left to act.
3. **After** the run, the evaluator inspects the filesystem and checks, against the ground truth: (a) the file exists at the expected path, (b) each expected tag is present in the YAML frontmatter, (c) each expected `[[link]]` is present in the body. The per-query score is `(tag_hits + link_hits) / (tags_total + links_total)`. `exact_match` requires every tag and every link present.

### B.3 Results

Run `20260529_152011`, `google/gemini-2.5-flash`, same vault. Each synthesis query is scored on the file the model wrote to disk (file location + frontmatter tags + body links).

Per-query outcome: **every synthesis query is an exact match under both configurations**:


| qid  | A exact | A links | A tags | A tool calls | B exact | B links | B tags | B tool calls |
| ---- | ------- | ------- | ------ | ------------ | ------- | ------- | ------ | ------------ |
| qs01 | ✓       | 3/3     | 2/2    | 1            | ✓       | 3/3     | 2/2    | 5            |
| qs02 | ✓       | 3/3     | 2/2    | 1            | ✓       | 3/3     | 2/2    | 5            |
| qs03 | ✓       | 3/3     | 2/2    | 1            | ✓       | 3/3     | 2/2    | 5            |


Aggregate (synthesis category only):


| Metric                     | Config A | Config B | B / A    |
| -------------------------- | -------- | -------- | -------- |
| Success rate (exact_match) | **1.00** | **1.00** | 1.0×     |
| Avg F1 (structural)        | **1.00** | **1.00** | 1.0×     |
| Avg tool calls             | 1.00     | 5.00     | **5.0×** |
| Avg tokens / query         | 2153     | 8491     | **3.9×** |
| Avg latency (s)            | 1.41     | 4.58     | **3.3×** |


Both interfaces produced perfectly correct notes on all three queries. The only difference was cost: Config B used **5× the tool calls, ~4× the tokens (+6338 per note) and ~3.3× the latency** to write a file identical in tags, links and location to the one Config A produced in a single call.

### B.4 Conclusion

Both configs were equally correct, so the only difference between them was cost. For a task with a clear structural target like this, granularity made no difference to quality.

The cost advantage of the coarse tool is small for reads but large for writes. Comparing the same run's retrieval queries against its synthesis queries:


|                  | A tool calls | B tool calls | B/A      | A tokens | B tokens | B/A      |
| ---------------- | ------------ | ------------ | -------- | -------- | -------- | -------- |
| Retrieval (25 q) | 1.00         | 1.28         | 1.3×     | 2223     | 3318     | 1.5×     |
| Synthesis (3 q)  | 1.00         | 5.00         | **5.0×** | 2153     | 8491     | **3.9×** |


For reads, Config B issues only ~0.28 extra calls and ~1.5× the tokens. For writes, that rises to 5× the calls and ~4× the tokens for the same result.

I expected fine grained creation to also lose accuracy (more calls, more chances to forget a link). The data did not show that. But it is still wasteful here, since it costs much more for the same result.

## Bonus: Testing Multiple LLMs

### C.1 Models

Three models on a capability gradient, all via OpenRouter with the customized prompts:


| Label          | OpenRouter slug                    | Run               |
| -------------- | ---------------------------------- | ----------------- |
| Strong         | `anthropic/claude-sonnet-4.6`      | `20260529_223238` |
| Mid (baseline) | `google/gemini-2.5-flash`          | `20260520_153009` |
| Small          | `meta-llama/llama-3.1-8b-instruct` | `20260529_230439` |


All three ran the same 25 retrieval queries (no synthesis).

### C.2 Results

Retrieval F1 and success rate, per model per config:


| Model             | A F1  | B F1      | B − A  | A success | B success | A tool calls | B tool calls | A tokens | B tokens |
| ----------------- | ----- | --------- | ------ | --------- | --------- | ------------ | ------------ | -------- | -------- |
| claude-sonnet-4.6 | 0.852 | **0.930** | +0.078 | 0.72      | 0.72      | 4.08         | 4.36         | 7658     | 9655     |
| gemini-2.5-flash  | 0.680 | 0.691     | +0.011 | 0.56      | 0.60      | 1.04         | 1.56         | 1888     | 2502     |
| llama-3.1-8b      | 0.218 | **0.407** | +0.189 | 0.20      | 0.36      | 3.44         | 2.28         | 7565     | 5564     |


Per-category F1 (Config B, the stronger config for every model):


| Model             | simple | tag  | temporal | content | multi_faceted | graph_based |
| ----------------- | ------ | ---- | -------- | ------- | ------------- | ----------- |
| claude-sonnet-4.6 | 1.00   | 1.00 | 1.00     | 1.00    | 0.94          | **0.83**    |
| gemini-2.5-flash  | 1.00   | 1.00 | 1.00     | 1.00    | 0.70          | 0.29        |
| llama-3.1-8b      | 0.00   | 0.50 | 1.00     | 1.00    | 0.35          | 0.14        |


### C.3 Findings

**1. The model matters most.** Changing the model moves F1 from 0.22 (Llama) to 0.93 (Sonnet), a gap of about 0.71. By comparison, the better prompts in Part 3 were worth about +0.34, and choosing A vs B within one model is worth at most +0.19 and as little as +0.01. So the order of importance is **model > prompt > tool granularity**. 

**2. Fine-grained tools (Config B) helped every model and helped the weakest one the most.** This is the opposite of what I expected. I thought the single coarse tool would help a weak model by asking less of it. Instead Config B beat Config A for all three models and the gap was biggest for Llama (+0.189). Llama's behavior shows why: a small model handles several simple one-parameter calls better than one `search_notes` call with four optional parameters. In Config A, Llama scored 0.00 on tag_search and 0.11 on multi_faceted, the narrow tools in Config B raised those to 0.50 and 0.35. Llama even made fewer calls in B (2.28) than in A (3.44), so Config A was not giving it more reasoning, it was just confusing it.

**3. The "A ≈ B tie" from Part 3.4 was true only for Gemini.** In Part 3.4, Gemini's two configs scored almost the same F1 (Config A 0.680, Config B 0.691, a difference of just 0.011), which is what made A and B look interchangeable. That near tie did not hold for the other models. For Sonnet, Config B beats Config A by 0.078, almost all of it from graph_based (0.53 in A, 0.83 in B). For Llama the gap is 0.189. So the main granularity finding does not carry over to other models: the more a model relies on hard relational queries, the more the fine-grained link tools help it.

**4. Cost depends on the model, not just the config.** Sonnet calls tools a lot: about 4 calls even in coarse Config A (Gemini makes 1.04) and 7.7k to 9.7k tokens per query. It reaches the best F1 but at roughly 4x to 5x Gemini's tokens and about 50% more time. Llama costs a medium amount but is inaccurate. So the choice depends on the budget:

- For low cost: Gemini Flash + Config A. F1 0.68 at 1888 tokens and about 1 tool call.
- For best accuracy: Sonnet + Config B. F1 0.93 at 9655 tokens and about 4.4 tool calls, roughly 5x the cost.

**5. graph_based is hard for every model.** All three scored lowest there (Llama 0.14, Gemini 0.29, Sonnet 0.83). Even the strong model is well short of the other categories, which supports Part 4.5: multi-hop link reasoning is the part of this task that a better model helps with most, but no model fully solves it.

### C.4 Limitations

- LLM output is not fully deterministic, so each number is a single run, not an average. The big gaps (the 0.71 spread across models) are safe to trust. The small gaps, like Gemini's 0.011 between A and B, are too small to mean much.

