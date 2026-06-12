---
name: scholarly-deep-research
description: Hybrid Deep Research workflow for scholarly literature retrieval and topic synthesis. Use when Codex needs to search papers, supplement with web evidence, and write a research-style briefing for literature reviews, related work, prior work, systematic review scoping, bibliography generation, research trend analysis, or evidence collection; supports OpenAlex, Semantic Scholar, Crossref, PubMed, arXiv, credential-gated IEEE Xplore, normalized CSV/JSON/BibTeX, Chinese topic briefs, search logs, and Codex-authored deep research reports.
---

# Scholarly Deep Research

## Overview

Use this skill to turn a research question into a reproducible literature retrieval run plus a Deep Research-style topic report. The bundled CLI creates the auditable academic corpus; Codex web search can then supplement that corpus with project pages, author pages, open PDFs, recent preprints, and reliable web context.

## Quick Start

Run the bundled Python CLI from this skill folder:

```powershell
python scripts/lit_retrieve.py --query "retrieval augmented generation for medical question answering" --from-year 2020 --to-year 2026 --limit 50 --sources openalex,semanticscholar,crossref,pubmed,arxiv --email user@example.com --report-language zh --report-style brief
```

For IEEE Xplore, include `ieee` in `--sources` and pass `--ieee-api-key`. If the key is missing, the CLI must skip IEEE and log the reason instead of failing.

## Hybrid Deep Research Workflow

1. Clarify the research question only when scope, domain, time range, or inclusion criteria are materially ambiguous.
2. Generate or refine broad, narrow, synonym, citation-oriented, and recent queries. See `references/deep-research-workflow.md`.
3. Run `scripts/lit_retrieve.py` for reproducible retrieval from official APIs.
4. Inspect `search_log.md` and `topic_brief.md` before making claims.
5. Use web search only as a supplement. Record supplemental pages in `web_supplement.md` with URL, source type, relevance, and reason for inclusion.
6. Write `deep_research_report.md` in Chinese by synthesizing `topic_brief.md`, `papers.json`, `search_log.md`, and `web_supplement.md`.
7. Keep API retrieval results and web supplement evidence separate. Do not silently merge web-only findings into `papers.json`.

## Outputs

Each run writes a timestamped output directory unless `--output-dir` is provided:

- `papers.csv`: normalized table for spreadsheet screening.
- `papers.json`: normalized records with scores and source metadata.
- `papers.bib`: BibTeX entries suitable for import into citation managers.
- `report.md`: Chinese topic brief by default, or ranked list when `--report-style list` is used.
- `topic_brief.md`: deterministic Chinese research briefing generated from retrieved metadata.
- `web_supplement.md`: Codex-authored supplemental web-search notes when a hybrid run is requested.
- `deep_research_report.md`: Codex-authored final synthesis when a hybrid run is requested.
- `search_log.md`: source parameters, counts, skipped sources, and ranking formula.
- `errors.log`: connector errors, only when failures occur.

## Data Model

Normalize paper records to:

`title`, `authors`, `year`, `venue`, `doi`, `arxiv_id`, `url`, `abstract`, `source`, `citation_count`, `is_open_access`, `open_access_url`, `publication_type`, `keywords`.

Deduplicate in this order:

1. DOI exact match.
2. arXiv ID exact match.
3. High normalized-title similarity.
4. Same normalized title, first author, and nearby year.

Rank with a transparent score combining lexical relevance, citation count, recency, venue/source confidence, and open-access signal. Treat ranking as a screening aid, not a scientific judgment.

## Report Expectations

For Deep Research-style outputs, emphasize the topic rather than the mechanics of search:

- Define the problem and why it matters.
- Group the literature into technical routes.
- Identify representative papers and their roles.
- Describe the research timeline and method evolution.
- Compare major method families.
- State limitations, open problems, and a recommended reading order.
- Cite paper metadata from `papers.json` and web evidence from `web_supplement.md`.

## Boundaries

- Use official APIs only.
- Do not scrape Google Scholar, ResearchGate, publisher pages, or paywalled PDFs.
- Do not claim the Python CLI has ChatGPT's internal web-search capability. Web search is a Codex workflow step, not a CLI connector.
- Do not claim exhaustive coverage unless the user provided a full review protocol, selected databases, exact queries, and inclusion criteria.
- State that results depend on API availability, source coverage, query quality, metadata quality, and credentials.
- Read `references/api-notes.md` when changing connector behavior, API parameters, or source-specific claims.
- Read `references/report-template-zh.md` before writing `deep_research_report.md`.
