# Deep Research Workflow

Use this reference when the user wants a topic report rather than a paper list.

## Query Expansion

Start from the user's query, then create complementary searches:

- Broad: `"<core topic>" review OR survey`
- Method: `"<method term>" "<domain term>" control`
- Metric: `"algebraic connectivity" "multi-agent"`, `"Fiedler eigenvalue" distributed control`
- Task: `"connectivity preservation" formation control`, `"connectivity maintenance" collision avoidance`
- Recent: add current-year window or `arXiv`
- Citation trail: search titles of highly ranked or high-citation papers

For multi-agent connectivity control, useful expansions include:

- `"multi-agent systems" "connectivity preservation" control`
- `"algebraic connectivity" "multi-agent" formation control`
- `"connectivity maintenance" "multi-robot" consensus`
- `"Fiedler eigenvalue" "distributed connectivity control"`
- `"connectivity preserving formation control" arXiv`

## Web Supplement

Use ordinary web search only after the API retrieval. Add findings to `web_supplement.md`, not to `papers.json`.

Look for:

- author pages and lab pages
- project pages and code repositories
- open PDFs and accepted versions
- recent arXiv/preprint pages
- conference pages and reliable publisher landing pages
- survey pages that clarify terminology

Do not scrape Google Scholar, ResearchGate, publisher pages, or paywalled PDFs. Google Scholar may be mentioned only as a manual check.

## Web Supplement Entry Format

```markdown
## Web Supplement

| Source | URL | Type | Relevance | Use in final report |
| --- | --- | --- | --- | --- |
| Author page | https://... | author/lab/project/pdf | Explains ... | Supports ... |
```

## Synthesis Rules

- Treat `papers.json` as the auditable academic corpus.
- Treat web results as context and gap-filling evidence.
- Do not imply web search is exhaustive.
- Separate "retrieved papers" from "web-only supplement" in the final report.
- Prefer DOI, arXiv ID, venue, year, and source URL for paper citations.
- Keep paper titles in English. Write analysis in Chinese unless the user asks otherwise.
