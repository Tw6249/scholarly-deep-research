#!/usr/bin/env python3
"""Retrieve scholarly literature from official APIs and export reproducible files."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Optional, Tuple


SOURCES = ("openalex", "semanticscholar", "crossref", "pubmed", "arxiv", "ieee")
RANKING_FORMULA = (
    "score = 0.40 * lexical_relevance + 0.20 * citation_score + "
    "0.15 * recency_score + 0.10 * venue_source_confidence + "
    "0.10 * open_access_score + 0.05 * metadata_completeness"
)


def main() -> int:
    args = parse_args()
    sources = parse_sources(args.sources)
    out_dir = args.output_dir or default_output_dir()
    os.makedirs(out_dir, exist_ok=True)

    logs: List[str] = []
    errors: List[str] = []
    skipped: List[str] = []
    all_records: List[Dict[str, Any]] = []
    raw_counts: Dict[str, int] = {}

    logs.append(f"# Search Log\n")
    logs.append(f"- Timestamp: {dt.datetime.now(dt.timezone.utc).isoformat()}")
    logs.append(f"- Query: {args.query}")
    logs.append(f"- Year range: {args.from_year or 'any'} to {args.to_year or 'any'}")
    logs.append(f"- Requested limit per source: {args.limit}")
    logs.append(f"- Sources: {', '.join(sources)}")

    for source in sources:
        if source == "ieee" and not args.ieee_api_key:
            skipped.append("ieee: missing --ieee-api-key")
            raw_counts[source] = 0
            continue
        try:
            records = fetch_source(source, args)
            raw_counts[source] = len(records)
            all_records.extend(records)
            time.sleep(args.delay)
        except Exception as exc:  # Keep one bad source from aborting the run.
            raw_counts[source] = 0
            errors.append(f"{source}: {type(exc).__name__}: {exc}")

    deduped, duplicate_notes = dedupe_records(all_records)
    ranked = rank_records(deduped, args.query, args.from_year, args.to_year)

    write_json(os.path.join(out_dir, "papers.json"), ranked)
    write_csv(os.path.join(out_dir, "papers.csv"), ranked)
    write_bibtex(os.path.join(out_dir, "papers.bib"), ranked)
    write_report(os.path.join(out_dir, "report.md"), ranked, args)
    write_topic_brief(os.path.join(out_dir, "topic_brief.md"), ranked, args, raw_counts, skipped, errors)
    write_search_log(
        os.path.join(out_dir, "search_log.md"),
        logs,
        raw_counts,
        len(all_records),
        len(deduped),
        duplicate_notes,
        skipped,
        errors,
    )
    if errors:
        with open(os.path.join(out_dir, "errors.log"), "w", encoding="utf-8") as f:
            f.write("\n".join(errors) + "\n")

    print(f"Wrote {len(ranked)} normalized records to {out_dir}")
    if skipped:
        print("Skipped: " + "; ".join(skipped))
    if errors:
        print(f"Completed with {len(errors)} connector error(s); see errors.log", file=sys.stderr)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Retrieve and rank scholarly literature.")
    parser.add_argument("--query", required=True, help="Research query or search expression.")
    parser.add_argument("--from-year", type=int, default=None, help="Inclusive start year.")
    parser.add_argument("--to-year", type=int, default=None, help="Inclusive end year.")
    parser.add_argument("--limit", type=int, default=50, help="Maximum records per source.")
    parser.add_argument(
        "--sources",
        default="openalex,semanticscholar,crossref,pubmed,arxiv",
        help="Comma-separated sources: openalex,semanticscholar,crossref,pubmed,arxiv,ieee.",
    )
    parser.add_argument("--email", default="", help="Contact email for polite API usage.")
    parser.add_argument("--ieee-api-key", default="", help="IEEE Xplore API key.")
    parser.add_argument("--ncbi-api-key", default="", help="Optional NCBI E-utilities API key.")
    parser.add_argument("--semantic-scholar-api-key", default="", help="Optional Semantic Scholar API key.")
    parser.add_argument("--output-dir", default="", help="Output directory. Defaults to outputs/<timestamp>.")
    parser.add_argument(
        "--report-language",
        choices=("zh", "en"),
        default="zh",
        help="Language for topic_brief.md. Default: zh.",
    )
    parser.add_argument(
        "--report-style",
        choices=("brief", "list"),
        default="brief",
        help="Report style for report.md. 'brief' writes a topic briefing; 'list' writes the legacy ranked list.",
    )
    parser.add_argument("--delay", type=float, default=0.35, help="Delay between source requests.")
    return parser.parse_args()


def parse_sources(raw: str) -> List[str]:
    values = [s.strip().lower() for s in raw.split(",") if s.strip()]
    unknown = [s for s in values if s not in SOURCES]
    if unknown:
        raise SystemExit(f"Unknown source(s): {', '.join(unknown)}")
    return values


def default_output_dir() -> str:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    return os.path.join(os.getcwd(), "outputs", stamp)


def fetch_source(source: str, args: argparse.Namespace) -> List[Dict[str, Any]]:
    if source == "openalex":
        return fetch_openalex(args)
    if source == "semanticscholar":
        return fetch_semantic_scholar(args)
    if source == "crossref":
        return fetch_crossref(args)
    if source == "pubmed":
        return fetch_pubmed(args)
    if source == "arxiv":
        return fetch_arxiv(args)
    if source == "ieee":
        return fetch_ieee(args)
    raise ValueError(source)


def http_json(url: str, headers: Optional[Dict[str, str]] = None, retries: int = 2) -> Dict[str, Any]:
    data = http_bytes(url, headers=headers, retries=retries)
    return json.loads(data.decode("utf-8"))


def http_text(url: str, headers: Optional[Dict[str, str]] = None, retries: int = 2) -> str:
    return http_bytes(url, headers=headers, retries=retries).decode("utf-8", errors="replace")


def http_bytes(url: str, headers: Optional[Dict[str, str]] = None, retries: int = 2) -> bytes:
    request = urllib.request.Request(url, headers=headers or {"User-Agent": "scholarly-deep-research-skill/1.0"})
    last_error: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
        except urllib.error.URLError as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
    raise RuntimeError(last_error)


def fetch_openalex(args: argparse.Namespace) -> List[Dict[str, Any]]:
    params = {"search": args.query, "per-page": str(args.limit)}
    filters = []
    if args.from_year:
        filters.append(f"from_publication_date:{args.from_year}-01-01")
    if args.to_year:
        filters.append(f"to_publication_date:{args.to_year}-12-31")
    if filters:
        params["filter"] = ",".join(filters)
    if args.email:
        params["mailto"] = args.email
    url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
    data = http_json(url)
    records = []
    for item in data.get("results", []):
        authors = [
            a.get("author", {}).get("display_name", "")
            for a in item.get("authorships", [])
            if a.get("author", {}).get("display_name")
        ]
        location = item.get("primary_location") or {}
        source = location.get("source") or {}
        open_access = item.get("open_access") or {}
        records.append(
            paper(
                title=item.get("title", ""),
                authors=authors,
                year=item.get("publication_year"),
                venue=source.get("display_name", ""),
                doi=clean_doi(item.get("doi", "")),
                url=item.get("doi") or item.get("id") or "",
                abstract=reconstruct_openalex_abstract(item.get("abstract_inverted_index")),
                source="openalex",
                citation_count=item.get("cited_by_count") or 0,
                is_open_access=bool(open_access.get("is_oa")),
                open_access_url=open_access.get("oa_url") or "",
                publication_type=item.get("type") or "",
                keywords=[c.get("display_name", "") for c in item.get("concepts", [])[:8] if c.get("display_name")],
            )
        )
    return records


def fetch_semantic_scholar(args: argparse.Namespace) -> List[Dict[str, Any]]:
    fields = ",".join(
        [
            "title",
            "authors",
            "year",
            "venue",
            "abstract",
            "citationCount",
            "isOpenAccess",
            "openAccessPdf",
            "externalIds",
            "url",
            "publicationTypes",
            "fieldsOfStudy",
        ]
    )
    params = {"query": args.query, "limit": str(min(args.limit, 100)), "fields": fields}
    if args.from_year or args.to_year:
        start = args.from_year or ""
        end = args.to_year or ""
        params["year"] = f"{start}-{end}"
    headers = {"User-Agent": "scholarly-deep-research-skill/1.0"}
    if args.semantic_scholar_api_key:
        headers["x-api-key"] = args.semantic_scholar_api_key
    url = "https://api.semanticscholar.org/graph/v1/paper/search?" + urllib.parse.urlencode(params)
    data = http_json(url, headers=headers)
    records = []
    for item in data.get("data", []):
        external = item.get("externalIds") or {}
        oa_pdf = item.get("openAccessPdf") or {}
        records.append(
            paper(
                title=item.get("title", ""),
                authors=[a.get("name", "") for a in item.get("authors", []) if a.get("name")],
                year=item.get("year"),
                venue=item.get("venue", ""),
                doi=clean_doi(external.get("DOI", "")),
                arxiv_id=external.get("ArXiv", ""),
                url=item.get("url", ""),
                abstract=item.get("abstract", ""),
                source="semanticscholar",
                citation_count=item.get("citationCount") or 0,
                is_open_access=bool(item.get("isOpenAccess")),
                open_access_url=oa_pdf.get("url", ""),
                publication_type=", ".join(item.get("publicationTypes") or []),
                keywords=item.get("fieldsOfStudy") or [],
            )
        )
    return records


def fetch_crossref(args: argparse.Namespace) -> List[Dict[str, Any]]:
    params = {"query": args.query, "rows": str(min(args.limit, 100))}
    filters = []
    if args.from_year:
        filters.append(f"from-pub-date:{args.from_year}-01-01")
    if args.to_year:
        filters.append(f"until-pub-date:{args.to_year}-12-31")
    if filters:
        params["filter"] = ",".join(filters)
    if args.email:
        params["mailto"] = args.email
    url = "https://api.crossref.org/works?" + urllib.parse.urlencode(params)
    data = http_json(url)
    records = []
    for item in data.get("message", {}).get("items", []):
        year = crossref_year(item)
        authors = []
        for author in item.get("author", []):
            name = " ".join([author.get("given", ""), author.get("family", "")]).strip()
            if name:
                authors.append(name)
        records.append(
            paper(
                title=first(item.get("title")),
                authors=authors,
                year=year,
                venue=first(item.get("container-title")),
                doi=clean_doi(item.get("DOI", "")),
                url=item.get("URL", ""),
                abstract=strip_tags(item.get("abstract", "")),
                source="crossref",
                citation_count=item.get("is-referenced-by-count") or 0,
                is_open_access=bool(item.get("license")),
                open_access_url=first([link.get("URL", "") for link in item.get("link", [])]),
                publication_type=item.get("type", ""),
                keywords=item.get("subject") or [],
            )
        )
    return records


def fetch_pubmed(args: argparse.Namespace) -> List[Dict[str, Any]]:
    term = args.query
    if args.from_year or args.to_year:
        start = args.from_year or 1800
        end = args.to_year or dt.datetime.now().year
        term = f"({term}) AND ({start}:{end}[dp])"
    base_params = {
        "db": "pubmed",
        "term": term,
        "retmax": str(args.limit),
        "retmode": "json",
        "tool": "scholarly-deep-research-skill",
    }
    if args.email:
        base_params["email"] = args.email
    if args.ncbi_api_key:
        base_params["api_key"] = args.ncbi_api_key
    esearch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?" + urllib.parse.urlencode(base_params)
    ids = http_json(esearch_url).get("esearchresult", {}).get("idlist", [])
    if not ids:
        return []
    time.sleep(max(args.delay, 0.34))
    efetch_params = {
        "db": "pubmed",
        "id": ",".join(ids),
        "retmode": "xml",
        "tool": "scholarly-deep-research-skill",
    }
    if args.email:
        efetch_params["email"] = args.email
    if args.ncbi_api_key:
        efetch_params["api_key"] = args.ncbi_api_key
    efetch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?" + urllib.parse.urlencode(efetch_params)
    root = ET.fromstring(http_text(efetch_url))
    records = []
    for article in root.findall(".//PubmedArticle"):
        medline = article.find("./MedlineCitation")
        art = article.find(".//Article")
        if art is None:
            continue
        ids_by_type = {}
        for article_id in article.findall(".//ArticleId"):
            id_type = article_id.attrib.get("IdType", "").lower()
            ids_by_type[id_type] = text(article_id)
        records.append(
            paper(
                title=text(art.find("./ArticleTitle")),
                authors=pubmed_authors(art),
                year=pubmed_year(art),
                venue=text(art.find("./Journal/Title")),
                doi=clean_doi(ids_by_type.get("doi", "")),
                url="https://pubmed.ncbi.nlm.nih.gov/" + (ids_by_type.get("pubmed") or text(medline.find("./PMID") if medline is not None else None)),
                abstract=" ".join(text(x) for x in art.findall("./Abstract/AbstractText") if text(x)),
                source="pubmed",
                citation_count=0,
                is_open_access=False,
                open_access_url="",
                publication_type=", ".join(text(x) for x in art.findall("./PublicationTypeList/PublicationType") if text(x)),
                keywords=[text(x) for x in article.findall(".//Keyword") if text(x)],
            )
        )
    return records


def fetch_arxiv(args: argparse.Namespace) -> List[Dict[str, Any]]:
    query = f"all:{args.query}"
    params = {
        "search_query": query,
        "start": "0",
        "max_results": str(min(args.limit, 100)),
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(params)
    root = ET.fromstring(http_text(url))
    ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    records = []
    for entry in root.findall("atom:entry", ns):
        published = text(entry.find("atom:published", ns))
        year = int(published[:4]) if published[:4].isdigit() else None
        if args.from_year and year and year < args.from_year:
            continue
        if args.to_year and year and year > args.to_year:
            continue
        links = entry.findall("atom:link", ns)
        pdf_url = ""
        html_url = text(entry.find("atom:id", ns))
        for link in links:
            if link.attrib.get("title") == "pdf":
                pdf_url = link.attrib.get("href", "")
        arxiv_id = html_url.rstrip("/").split("/")[-1]
        records.append(
            paper(
                title=compact_ws(text(entry.find("atom:title", ns))),
                authors=[text(a.find("atom:name", ns)) for a in entry.findall("atom:author", ns) if text(a.find("atom:name", ns))],
                year=year,
                venue="arXiv",
                doi=clean_doi(text(entry.find("arxiv:doi", ns))),
                arxiv_id=arxiv_id,
                url=html_url,
                abstract=compact_ws(text(entry.find("atom:summary", ns))),
                source="arxiv",
                citation_count=0,
                is_open_access=True,
                open_access_url=pdf_url or html_url,
                publication_type="preprint",
                keywords=[text(c) for c in entry.findall("atom:category", ns) if text(c)],
            )
        )
    return records


def fetch_ieee(args: argparse.Namespace) -> List[Dict[str, Any]]:
    params = {
        "apikey": args.ieee_api_key,
        "format": "json",
        "max_records": str(min(args.limit, 200)),
        "start_record": "1",
        "sort_order": "desc",
        "sort_field": "article_number",
        "querytext": args.query,
    }
    if args.from_year:
        params["start_year"] = str(args.from_year)
    if args.to_year:
        params["end_year"] = str(args.to_year)
    url = "https://ieeexploreapi.ieee.org/api/v1/search/articles?" + urllib.parse.urlencode(params)
    data = http_json(url)
    records = []
    for item in data.get("articles", []):
        authors_obj = item.get("authors") or {}
        authors = [a.get("full_name", "") for a in authors_obj.get("authors", []) if a.get("full_name")]
        records.append(
            paper(
                title=item.get("title", ""),
                authors=authors,
                year=to_int(item.get("publication_year")),
                venue=item.get("publication_title", ""),
                doi=clean_doi(item.get("doi", "")),
                url=item.get("html_url") or item.get("pdf_url") or "",
                abstract=item.get("abstract", ""),
                source="ieee",
                citation_count=to_int(item.get("citing_paper_count")) or 0,
                is_open_access=bool(item.get("open_access")),
                open_access_url=item.get("pdf_url", "") if item.get("open_access") else "",
                publication_type=item.get("content_type", ""),
                keywords=ieee_keywords(item),
            )
        )
    return records


def paper(**kwargs: Any) -> Dict[str, Any]:
    data = {
        "title": "",
        "authors": [],
        "year": None,
        "venue": "",
        "doi": "",
        "arxiv_id": "",
        "url": "",
        "abstract": "",
        "source": "",
        "citation_count": 0,
        "is_open_access": False,
        "open_access_url": "",
        "publication_type": "",
        "keywords": [],
    }
    data.update(kwargs)
    data["title"] = compact_ws(html.unescape(str(data.get("title") or "")))
    data["abstract"] = compact_ws(html.unescape(str(data.get("abstract") or "")))
    data["authors"] = [compact_ws(str(a)) for a in data.get("authors") or [] if compact_ws(str(a))]
    data["keywords"] = [compact_ws(str(k)) for k in data.get("keywords") or [] if compact_ws(str(k))]
    data["year"] = to_int(data.get("year"))
    data["citation_count"] = to_int(data.get("citation_count")) or 0
    data["doi"] = clean_doi(data.get("doi", ""))
    data["arxiv_id"] = clean_arxiv_id(data.get("arxiv_id", ""))
    return data


def dedupe_records(records: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str]]:
    unique: List[Dict[str, Any]] = []
    notes: List[str] = []
    doi_index: Dict[str, int] = {}
    arxiv_index: Dict[str, int] = {}

    for record in records:
        doi = record.get("doi") or ""
        arxiv_id = record.get("arxiv_id") or ""
        if doi and doi in doi_index:
            merge_record(unique[doi_index[doi]], record)
            notes.append(f"DOI duplicate: {doi}")
            continue
        if arxiv_id and arxiv_id in arxiv_index:
            merge_record(unique[arxiv_index[arxiv_id]], record)
            notes.append(f"arXiv duplicate: {arxiv_id}")
            continue

        duplicate_at = find_title_duplicate(unique, record)
        if duplicate_at is not None:
            merge_record(unique[duplicate_at], record)
            notes.append(f"Title duplicate: {record.get('title', '')[:120]}")
            continue

        index = len(unique)
        unique.append(record)
        if doi:
            doi_index[doi] = index
        if arxiv_id:
            arxiv_index[arxiv_id] = index
    return unique, notes


def find_title_duplicate(unique: List[Dict[str, Any]], record: Dict[str, Any]) -> Optional[int]:
    title = normalize_title(record.get("title", ""))
    if not title:
        return None
    first_author = normalize_author(first(record.get("authors", [])))
    year = record.get("year")
    for idx, other in enumerate(unique):
        other_title = normalize_title(other.get("title", ""))
        if not other_title:
            continue
        ratio = SequenceMatcher(None, title, other_title).ratio()
        if ratio >= 0.94:
            return idx
        other_author = normalize_author(first(other.get("authors", [])))
        other_year = other.get("year")
        years_close = year and other_year and abs(int(year) - int(other_year)) <= 1
        if ratio >= 0.88 and first_author and first_author == other_author and years_close:
            return idx
    return None


def merge_record(base: Dict[str, Any], incoming: Dict[str, Any]) -> None:
    base.setdefault("sources", [base.get("source", "")])
    if incoming.get("source") and incoming.get("source") not in base["sources"]:
        base["sources"].append(incoming["source"])
    for key in ("abstract", "venue", "url", "open_access_url", "publication_type"):
        if not base.get(key) and incoming.get(key):
            base[key] = incoming[key]
    if incoming.get("citation_count", 0) > base.get("citation_count", 0):
        base["citation_count"] = incoming["citation_count"]
    base["is_open_access"] = bool(base.get("is_open_access") or incoming.get("is_open_access"))
    base["keywords"] = sorted(set((base.get("keywords") or []) + (incoming.get("keywords") or [])))
    base["authors"] = base.get("authors") or incoming.get("authors") or []


def rank_records(records: List[Dict[str, Any]], query: str, from_year: Optional[int], to_year: Optional[int]) -> List[Dict[str, Any]]:
    now_year = dt.datetime.now().year
    query_terms = set(tokenize(query))
    max_cites = max([r.get("citation_count", 0) for r in records] or [0])
    for record in records:
        haystack = " ".join(
            [
                record.get("title", ""),
                record.get("abstract", ""),
                " ".join(record.get("keywords", [])),
            ]
        )
        terms = set(tokenize(haystack))
        relevance = len(query_terms & terms) / max(len(query_terms), 1)
        citation_score = math.log1p(record.get("citation_count", 0)) / math.log1p(max_cites) if max_cites else 0.0
        year = record.get("year") or from_year or now_year - 10
        recency_score = max(0.0, min(1.0, 1.0 - ((now_year - int(year)) / 15.0)))
        confidence = source_confidence(record)
        oa_score = 1.0 if record.get("is_open_access") else 0.0
        completeness = metadata_completeness(record)
        score = 0.40 * relevance + 0.20 * citation_score + 0.15 * recency_score + 0.10 * confidence + 0.10 * oa_score + 0.05 * completeness
        record["score"] = round(score, 4)
        record.setdefault("sources", [record.get("source", "")])
    records.sort(key=lambda r: (r.get("score", 0), r.get("citation_count", 0), r.get("year") or 0), reverse=True)
    return records


def source_confidence(record: Dict[str, Any]) -> float:
    sources = set(record.get("sources") or [record.get("source", "")])
    base = {
        "openalex": 0.85,
        "semanticscholar": 0.85,
        "crossref": 0.8,
        "pubmed": 0.9,
        "arxiv": 0.75,
        "ieee": 0.85,
    }
    best = max([base.get(s, 0.5) for s in sources] or [0.5])
    if len(sources) > 1:
        best = min(1.0, best + 0.1)
    return best


def metadata_completeness(record: Dict[str, Any]) -> float:
    fields = ["title", "authors", "year", "venue", "doi", "url", "abstract"]
    return sum(1 for f in fields if record.get(f)) / len(fields)


def write_json(path: str, records: List[Dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def write_csv(path: str, records: List[Dict[str, Any]]) -> None:
    fields = [
        "score",
        "title",
        "authors",
        "year",
        "venue",
        "doi",
        "arxiv_id",
        "url",
        "abstract",
        "source",
        "sources",
        "citation_count",
        "is_open_access",
        "open_access_url",
        "publication_type",
        "keywords",
    ]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            row = dict(record)
            row["authors"] = "; ".join(record.get("authors") or [])
            row["sources"] = "; ".join(record.get("sources") or [record.get("source", "")])
            row["keywords"] = "; ".join(record.get("keywords") or [])
            writer.writerow(row)


def write_bibtex(path: str, records: List[Dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for idx, record in enumerate(records, start=1):
            key = bib_key(record, idx)
            kind = "article" if record.get("venue") and record.get("venue") != "arXiv" else "misc"
            f.write(f"@{kind}{{{key},\n")
            bib_fields = {
                "title": record.get("title", ""),
                "author": " and ".join(record.get("authors") or []),
                "year": record.get("year") or "",
                "journal": record.get("venue", ""),
                "doi": record.get("doi", ""),
                "url": record.get("url", ""),
            }
            for field, value in bib_fields.items():
                if value:
                    f.write(f"  {field} = {{{escape_bibtex(str(value))}}},\n")
            f.write("}\n\n")


def write_report(path: str, records: List[Dict[str, Any]], args: argparse.Namespace) -> None:
    if args.report_style == "brief":
        write_topic_brief(path, records, args, {}, [], [])
        return
    write_ranked_list_report(path, records, args)


def write_ranked_list_report(path: str, records: List[Dict[str, Any]], args: argparse.Namespace) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write("# Scholarly Deep Research Retrieval Report\n\n")
        f.write(f"- Query: {args.query}\n")
        f.write(f"- Year range: {args.from_year or 'any'} to {args.to_year or 'any'}\n")
        f.write(f"- Records after deduplication: {len(records)}\n")
        f.write(f"- Ranking: {RANKING_FORMULA}\n\n")
        f.write("## Ranked Papers\n\n")
        for i, record in enumerate(records, start=1):
            authors = ", ".join(record.get("authors")[:4])
            if len(record.get("authors") or []) > 4:
                authors += ", et al."
            f.write(f"### {i}. {record.get('title') or 'Untitled'}\n\n")
            f.write(f"- Score: {record.get('score')}\n")
            f.write(f"- Authors: {authors or 'Unknown'}\n")
            f.write(f"- Year / Venue: {record.get('year') or 'n.d.'} / {record.get('venue') or 'Unknown'}\n")
            f.write(f"- DOI: {record.get('doi') or 'None'}\n")
            f.write(f"- Sources: {', '.join(record.get('sources') or [record.get('source', '')])}\n")
            f.write(f"- Citations: {record.get('citation_count', 0)}\n")
            f.write(f"- URL: {record.get('url') or record.get('open_access_url') or 'None'}\n")
            if record.get("abstract"):
                f.write(f"- Abstract: {record['abstract'][:700]}\n")
            f.write("\n")
        f.write("## Coverage Note\n\n")
        f.write("This report supports screening and does not guarantee exhaustive coverage. Final scholarly use requires human review.\n")


def write_topic_brief(
    path: str,
    records: List[Dict[str, Any]],
    args: argparse.Namespace,
    raw_counts: Dict[str, int],
    skipped: List[str],
    errors: List[str],
) -> None:
    if args.report_language == "en":
        write_topic_brief_en(path, records, args, raw_counts, skipped, errors)
        return

    themes = theme_groups(records)
    top_records = records[:12]
    seminal = sorted(records, key=lambda r: (r.get("citation_count", 0), r.get("score", 0)), reverse=True)[:8]
    recent = sorted([r for r in records if r.get("year")], key=lambda r: (r.get("year") or 0, r.get("score", 0)), reverse=True)[:8]

    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# 主题调研简报：{args.query}\n\n")
        f.write("## 一句话结论\n\n")
        f.write(topic_takeaway(args.query, records, themes) + "\n\n")
        f.write("## 背景与问题定义\n\n")
        f.write(
            "本简报基于可复现学术 API 检索生成，用于快速理解一个研究主题的核心问题、代表工作和后续阅读路径。"
            "在多智能体系统语境下，连通度控制通常关注通信图或感知图在运动、编队、避障、攻击、事件触发通信等条件下能否保持足够连通，"
            "常见度量包括图连通性、Laplacian 的 algebraic connectivity、邻接边保持、有限感知半径内的连通维护等。\n\n"
        )
        f.write("## 检索策略与覆盖范围\n\n")
        f.write(f"- 原始查询：`{args.query}`\n")
        f.write(f"- 年份范围：{args.from_year or '不限'} 到 {args.to_year or '不限'}\n")
        f.write(f"- 去重后文献数：{len(records)}\n")
        if raw_counts:
            f.write("- 各源返回数量：" + ", ".join(f"{k}={v}" for k, v in raw_counts.items()) + "\n")
        if skipped:
            f.write("- 跳过来源：" + "; ".join(skipped) + "\n")
        if errors:
            f.write("- 检索错误：" + "; ".join(errors) + "\n")
        f.write(
            "- 说明：该结果依赖 API 覆盖、查询式质量和元数据完整度；最终用于论文写作前仍需人工筛选全文。\n\n"
        )

        f.write("## 技术路线分类\n\n")
        for label, items in themes.items():
            if not items:
                continue
            f.write(f"### {label}\n\n")
            f.write(theme_summary(label, items) + "\n\n")
            for paper_item in items[:5]:
                f.write(f"- {paper_line(paper_item)}\n")
            f.write("\n")

        f.write("## 代表性论文表\n\n")
        f.write("| 角色 | 论文 | 年份 | 来源/期刊会议 | 为什么重要 |\n")
        f.write("| --- | --- | --- | --- | --- |\n")
        for record in top_records[:10]:
            f.write(
                f"| {paper_role(record)} | {safe_cell(record.get('title'))} | {record.get('year') or 'n.d.'} | "
                f"{safe_cell(record.get('venue') or ', '.join(record.get('sources') or []))} | {safe_cell(why_important(record))} |\n"
            )
        f.write("\n")

        f.write("## 研究脉络\n\n")
        for line in timeline_lines(records):
            f.write(f"- {line}\n")
        f.write("\n")

        f.write("## 主要方法对比\n\n")
        f.write("| 方法族 | 典型关注点 | 优势 | 常见限制 |\n")
        f.write("| --- | --- | --- | --- |\n")
        f.write("| Potential/barrier/navigation functions | 保持已有边、避免距离约束破坏 | 直观，适合编队与避障 | 参数调节和局部极值问题明显 |\n")
        f.write("| Algebraic connectivity / Fiedler value | 直接优化或估计图连通度 | 能刻画全局连通裕度 | 分布式估计和可扩展性是难点 |\n")
        f.write("| Event-triggered connectivity control | 减少通信和控制更新 | 适合资源受限网络 | 需要证明无 Zeno 行为和鲁棒性 |\n")
        f.write("| Prescribed performance / constrained control | 把连通、碰撞、误差约束统一处理 | 约束表达清晰 | 对模型假设和扰动界较敏感 |\n")
        f.write("| MPC / optimization-based methods | 在预测窗口内优化连通和任务性能 | 可处理多目标权衡 | 计算量和实时性压力较高 |\n\n")

        f.write("## 重要论文阅读顺序\n\n")
        for i, record in enumerate(reading_order(seminal, recent, records), start=1):
            f.write(f"{i}. {paper_line(record)}\n")
        f.write("\n")

        f.write("## 局限与开放问题\n\n")
        for gap in research_gaps(records):
            f.write(f"- {gap}\n")
        f.write("\n")

        f.write("## 网页补充建议\n\n")
        for query in web_supplement_queries(args.query):
            f.write(f"- `{query}`\n")
        f.write(
            "\n将网页搜索结果单独记录到 `web_supplement.md`，只收录作者主页、项目页、开放 PDF、近期预印本、实验室页面和可靠综述资料；"
            "不要把 Google Scholar 抓取结果混入 API 检索语料。\n\n"
        )

        f.write("## 可复核来源\n\n")
        f.write("- `papers.json`：归一化元数据和排序分数。\n")
        f.write("- `papers.csv`：适合人工筛选的表格。\n")
        f.write("- `papers.bib`：BibTeX 导入文件。\n")
        f.write("- `search_log.md`：检索参数、来源计数、去重和跳过信息。\n")


def write_topic_brief_en(
    path: str,
    records: List[Dict[str, Any]],
    args: argparse.Namespace,
    raw_counts: Dict[str, int],
    skipped: List[str],
    errors: List[str],
) -> None:
    themes = theme_groups(records)
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# Topic Brief: {args.query}\n\n")
        f.write("## Takeaway\n\n")
        f.write(topic_takeaway(args.query, records, themes, language="en") + "\n\n")
        f.write("## Search Scope\n\n")
        f.write(f"- Query: `{args.query}`\n")
        f.write(f"- Year range: {args.from_year or 'any'} to {args.to_year or 'any'}\n")
        f.write(f"- Deduplicated records: {len(records)}\n")
        if raw_counts:
            f.write("- Source counts: " + ", ".join(f"{k}={v}" for k, v in raw_counts.items()) + "\n")
        if skipped:
            f.write("- Skipped: " + "; ".join(skipped) + "\n")
        if errors:
            f.write("- Errors: " + "; ".join(errors) + "\n")
        f.write("\n## Themes\n\n")
        for label, items in themes.items():
            if items:
                f.write(f"### {label}\n\n")
                for record in items[:5]:
                    f.write(f"- {paper_line(record)}\n")
                f.write("\n")
        f.write("## Recommended Reading Order\n\n")
        for i, record in enumerate(reading_order(records[:8], records[:8], records), start=1):
            f.write(f"{i}. {paper_line(record)}\n")


def write_search_log(
    path: str,
    header_lines: List[str],
    raw_counts: Dict[str, int],
    raw_total: int,
    deduped_total: int,
    duplicate_notes: List[str],
    skipped: List[str],
    errors: List[str],
) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(header_lines) + "\n\n")
        f.write("## Source Counts\n\n")
        for source in SOURCES:
            if source in raw_counts:
                f.write(f"- {source}: {raw_counts[source]}\n")
        f.write(f"\n- Total before deduplication: {raw_total}\n")
        f.write(f"- Total after deduplication: {deduped_total}\n")
        f.write(f"- Ranking formula: {RANKING_FORMULA}\n")
        if skipped:
            f.write("\n## Skipped Sources\n\n")
            for item in skipped:
                f.write(f"- {item}\n")
        if duplicate_notes:
            f.write("\n## Deduplication Notes\n\n")
            for note in duplicate_notes[:200]:
                f.write(f"- {note}\n")
        if errors:
            f.write("\n## Errors\n\n")
            for error in errors:
                f.write(f"- {error}\n")


def theme_groups(records: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    labels = {
        "连通度保持与代数连通度控制": ["connectivity", "algebraic", "laplacian", "fiedler", "network"],
        "编队、队形与一致性控制": ["formation", "consensus", "flocking", "tracking", "cooperative"],
        "避障、安全约束与有限感知": ["collision", "obstacle", "avoidance", "safety", "constraint", "bounded", "sensing"],
        "事件触发、通信受限与分布式实现": ["event", "triggered", "distributed", "decentralized", "communication"],
        "鲁棒性、攻击与不确定系统": ["attack", "uncertain", "disturbance", "robust", "nonlinear", "saturation"],
        "优化、MPC 与性能约束": ["optimal", "optimization", "predictive", "mpc", "prescribed", "performance"],
        "综述、基础理论与背景材料": ["survey", "review", "overview", "foundations", "trend"],
    }
    grouped: Dict[str, List[Dict[str, Any]]] = {label: [] for label in labels}
    grouped["其他相关工作"] = []
    for record in records:
        text_blob = " ".join(
            [
                record.get("title", ""),
                record.get("abstract", ""),
                record.get("venue", ""),
                " ".join(record.get("keywords") or []),
            ]
        ).lower()
        matched = False
        for label, keywords in labels.items():
            if any(keyword in text_blob for keyword in keywords):
                grouped[label].append(record)
                matched = True
        if not matched:
            grouped["其他相关工作"].append(record)
    for label in grouped:
        grouped[label] = sorted(
            dedupe_by_title(grouped[label]),
            key=lambda r: (r.get("score", 0), r.get("citation_count", 0)),
            reverse=True,
        )
    return grouped


def dedupe_by_title(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    result = []
    for record in records:
        key = normalize_title(record.get("title", ""))
        if key and key not in seen:
            seen.add(key)
            result.append(record)
    return result


def topic_takeaway(
    query: str,
    records: List[Dict[str, Any]],
    themes: Dict[str, List[Dict[str, Any]]],
    language: str = "zh",
) -> str:
    active = [label for label, items in themes.items() if items]
    years = [r.get("year") for r in records if r.get("year")]
    year_span = f"{min(years)}-{max(years)}" if years else "unknown years"
    if language == "en":
        return (
            f"The retrieved corpus for `{query}` suggests a control-oriented topic centered on maintaining graph "
            f"connectivity while satisfying formation, consensus, safety, communication, and robustness constraints "
            f"({len(records)} deduplicated records, {year_span})."
        )
    return (
        f"`{query}` 的检索结果显示，该主题的主线不是单纯的多智能体一致性，而是在编队、避障、通信受限、攻击或不确定性下"
        f"维持通信/感知图的连通裕度。当前语料包含 {len(records)} 条去重记录，年份覆盖 {year_span}，主要落在"
        f"{'、'.join(active[:5])}等方向。"
    )


def theme_summary(label: str, items: List[Dict[str, Any]]) -> str:
    top = items[0] if items else {}
    year_values = [r.get("year") for r in items if r.get("year")]
    year_span = f"{min(year_values)}-{max(year_values)}" if year_values else "年份不详"
    return (
        f"该类包含 {len(items)} 条候选文献，覆盖 {year_span}。排名靠前的代表工作是"
        f"《{top.get('title', 'Untitled')}》，可作为进入该分支的入口。"
    )


def paper_line(record: Dict[str, Any]) -> str:
    authors = ", ".join((record.get("authors") or [])[:3])
    if len(record.get("authors") or []) > 3:
        authors += ", et al."
    venue = record.get("venue") or ", ".join(record.get("sources") or []) or "Unknown venue"
    doi = record.get("doi") or record.get("arxiv_id") or "-"
    return (
        f"{record.get('title') or 'Untitled'} ({record.get('year') or 'n.d.'}), "
        f"{authors or 'Unknown authors'}, {venue}; citations={record.get('citation_count', 0)}, DOI/ID={doi}."
    )


def paper_role(record: Dict[str, Any]) -> str:
    text_blob = " ".join([record.get("title", ""), record.get("abstract", ""), record.get("venue", "")]).lower()
    if "survey" in text_blob or "review" in text_blob:
        return "综述入口"
    if record.get("citation_count", 0) >= 100:
        return "高被引基础"
    if "event" in text_blob:
        return "事件触发"
    if "collision" in text_blob or "obstacle" in text_blob:
        return "安全约束"
    if "algebraic" in text_blob or "laplacian" in text_blob or "fiedler" in text_blob:
        return "连通度度量"
    if (record.get("year") or 0) >= dt.datetime.now().year - 3:
        return "近期进展"
    return "代表工作"


def why_important(record: Dict[str, Any]) -> str:
    role = paper_role(record)
    if role == "高被引基础":
        return "引用量较高，适合作为理论背景或问题定义入口。"
    if role == "综述入口":
        return "覆盖面广，适合快速建立术语和分支地图。"
    if role == "事件触发":
        return "连接连通度保持与低通信/低更新频率实现。"
    if role == "安全约束":
        return "把连通保持与碰撞/障碍物约束放在同一控制问题中。"
    if role == "连通度度量":
        return "直接围绕图 Laplacian、代数连通度或 Fiedler 值建模。"
    if role == "近期进展":
        return "反映近年约束控制、鲁棒性或应用场景的新变化。"
    return "与主题词和核心技术路线高度相关，可作为分支阅读材料。"


def timeline_lines(records: List[Dict[str, Any]]) -> List[str]:
    lines = []
    buckets = [
        ("2010-2014", 2010, 2014),
        ("2015-2018", 2015, 2018),
        ("2019-2022", 2019, 2022),
        ("2023-2026", 2023, 2026),
    ]
    for label, start, end in buckets:
        items = [r for r in records if r.get("year") and start <= int(r["year"]) <= end]
        if not items:
            continue
        top = sorted(items, key=lambda r: (r.get("citation_count", 0), r.get("score", 0)), reverse=True)[0]
        lines.append(f"{label}：约 {len(items)} 条；代表工作为《{top.get('title')}》，该阶段重点可从 {paper_role(top)} 切入。")
    if not lines:
        lines.append("当前检索结果缺少年份信息，建议扩大来源或人工补充元数据后再判断脉络。")
    return lines


def reading_order(
    seminal: List[Dict[str, Any]],
    recent: List[Dict[str, Any]],
    records: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    selected: List[Dict[str, Any]] = []
    for pool in (seminal, records, recent):
        for record in pool:
            key = normalize_title(record.get("title", ""))
            if key and all(normalize_title(r.get("title", "")) != key for r in selected):
                selected.append(record)
            if len(selected) >= 10:
                return selected
    return selected


def research_gaps(records: List[Dict[str, Any]]) -> List[str]:
    text_blob = " ".join([r.get("title", "") + " " + r.get("abstract", "") for r in records]).lower()
    gaps = [
        "从理论保证走向真实机器人/无人系统实验仍是关键缺口，尤其是有限感知、通信丢包和动态障碍同时存在时。",
        "代数连通度类方法需要更可扩展的分布式估计与控制实现，避免全局谱信息成为隐含假设。",
        "连通保持、碰撞避免、队形精度和能耗之间存在多目标冲突，需要更清晰的权衡机制。",
        "事件触发和通信受限控制需要同时说明无 Zeno、鲁棒性和实际网络延迟下的性能。",
        "面向攻击或故障的连通度控制还需要把安全检测、拓扑重构和控制律设计更紧密地结合。",
    ]
    if "learning" not in text_blob and "neural" not in text_blob:
        gaps.append("学习方法与经典连通度控制的结合在当前检索中不突出，可作为补充检索方向。")
    if "experiment" not in text_blob and "robot" not in text_blob:
        gaps.append("当前元数据中实验/机器人关键词较少，建议网页补充检索项目页、视频和开源实现。")
    return gaps


def web_supplement_queries(query: str) -> List[str]:
    return [
        f'"{query}" PDF',
        '"multi-agent systems" "connectivity preservation" control',
        '"algebraic connectivity" "multi-agent" formation control',
        '"connectivity maintenance" "multi-robot" consensus',
        '"Fiedler eigenvalue" "distributed connectivity control"',
        '"connectivity preserving formation control" author page',
        '"multi-agent connectivity control" arXiv',
    ]


def safe_cell(value: Any) -> str:
    return compact_ws(str(value or "")).replace("|", "\\|")


def reconstruct_openalex_abstract(index: Optional[Dict[str, List[int]]]) -> str:
    if not index:
        return ""
    pairs = []
    for word, positions in index.items():
        for position in positions:
            pairs.append((position, word))
    return " ".join(word for _, word in sorted(pairs))


def crossref_year(item: Dict[str, Any]) -> Optional[int]:
    for key in ("published-print", "published-online", "published", "issued", "created"):
        parts = item.get(key, {}).get("date-parts")
        if parts and parts[0]:
            return to_int(parts[0][0])
    return None


def pubmed_authors(article: ET.Element) -> List[str]:
    names = []
    for author in article.findall("./AuthorList/Author"):
        collective = text(author.find("./CollectiveName"))
        if collective:
            names.append(collective)
            continue
        given = text(author.find("./ForeName")) or text(author.find("./Initials"))
        family = text(author.find("./LastName"))
        name = " ".join([given, family]).strip()
        if name:
            names.append(name)
    return names


def pubmed_year(article: ET.Element) -> Optional[int]:
    for path in ("./Journal/JournalIssue/PubDate/Year", "./ArticleDate/Year"):
        value = text(article.find(path))
        if value and value[:4].isdigit():
            return int(value[:4])
    medline_date = text(article.find("./Journal/JournalIssue/PubDate/MedlineDate"))
    match = re.search(r"(19|20)\d{2}", medline_date)
    return int(match.group(0)) if match else None


def ieee_keywords(item: Dict[str, Any]) -> List[str]:
    terms = []
    for value in (item.get("index_terms") or {}).values():
        if isinstance(value, dict):
            terms.extend(value.get("terms") or [])
        elif isinstance(value, list):
            terms.extend(value)
    return terms


def clean_doi(value: Any) -> str:
    value = str(value or "").strip()
    value = re.sub(r"^https?://(dx\.)?doi\.org/", "", value, flags=re.I)
    value = value.replace("doi:", "").strip()
    return value.lower()


def clean_arxiv_id(value: Any) -> str:
    value = str(value or "").strip()
    value = re.sub(r"^arxiv:", "", value, flags=re.I)
    value = value.replace("https://arxiv.org/abs/", "")
    return value


def normalize_title(value: str) -> str:
    return " ".join(tokenize(value))


def normalize_author(value: str) -> str:
    tokens = tokenize(value)
    return tokens[-1] if tokens else ""


def tokenize(value: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", (value or "").lower())


def strip_tags(value: str) -> str:
    return compact_ws(re.sub(r"<[^>]+>", " ", value or ""))


def compact_ws(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def text(node: Optional[ET.Element]) -> str:
    if node is None:
        return ""
    return compact_ws("".join(node.itertext()))


def first(value: Any) -> str:
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return str(value or "")


def to_int(value: Any) -> Optional[int]:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        match = re.search(r"\d+", str(value))
        return int(match.group(0)) if match else None


def bib_key(record: Dict[str, Any], idx: int) -> str:
    author = normalize_author(first(record.get("authors", []))) or "paper"
    year = record.get("year") or "nd"
    title_token = first(tokenize(record.get("title", ""))) or str(idx)
    return re.sub(r"[^A-Za-z0-9_:-]", "", f"{author}{year}{title_token}")


def escape_bibtex(value: str) -> str:
    return value.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


if __name__ == "__main__":
    raise SystemExit(main())
