# API Notes

Use these notes when maintaining `scripts/lit_retrieve.py` or explaining source coverage. Always prefer official API documentation and official public endpoints.

## Sources

- OpenAlex: official works API; no key required. Include `mailto` when an email is available. Useful fields include title, publication year/date, DOI, authorships, host venue/source, cited-by count, open-access metadata, concepts/topics, and inverted-index abstracts.
- Semantic Scholar: official Academic Graph API. No key is required for light use, but authenticated use may receive better rate limits. Paper search supports selected fields such as title, authors, year, venue, abstract, citation count, external IDs, open-access PDF metadata, and fields of study.
- Crossref: official REST API. Use a polite `mailto` parameter when available. It is strong for DOI and publisher metadata, but abstracts and citation counts are often absent.
- PubMed: use NCBI E-utilities, especially `esearch.fcgi` and `efetch.fcgi`, not web scraping. Include `email` and optional `api_key` when available.
- arXiv: use the official Atom API. It is strong for preprints in CS, math, physics, statistics, and adjacent fields. Citation counts are not available from arXiv.
- IEEE Xplore: use the official IEEE Xplore API and require an API key. If no key is supplied, skip and log rather than attempting alternate scraping.

## Compliance

- Never scrape Google Scholar, ResearchGate, publisher pages, or paywalled PDFs.
- Never bypass API limits or access controls.
- Keep a search log with timestamp, query, source list, parameters, returned counts, deduplication counts, skipped sources, and ranking formula.
- Treat retrieved metadata as screening evidence. Require human review before final inclusion in a publication or systematic review.

## Connector Expectations

- Each connector should fail independently and return an error entry rather than aborting the entire run.
- Normalize all connector records into the shared schema before deduplication.
- Preserve enough source metadata in JSON for traceability without storing full raw API payloads.
- Use conservative rate limiting between requests, especially for PubMed and arXiv.
