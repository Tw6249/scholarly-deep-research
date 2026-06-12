#!/usr/bin/env python3
"""Trace a seed paper's predecessors, follow-up work, deep citations, and author trajectories."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


S2_FIELDS = (
    "paperId,title,year,venue,abstract,citationCount,referenceCount,authors,"
    "externalIds,url,openAccessPdf,fieldsOfStudy,publicationTypes"
)
S2_REFERENCE_FIELDS = (
    "contexts,intents,isInfluential,"
    "citedPaper.paperId,citedPaper.title,citedPaper.year,citedPaper.venue,citedPaper.abstract,"
    "citedPaper.citationCount,citedPaper.authors,citedPaper.externalIds,citedPaper.url,citedPaper.openAccessPdf"
)
S2_CITATION_FIELDS = (
    "contexts,intents,isInfluential,"
    "citingPaper.paperId,citingPaper.title,citingPaper.year,citingPaper.venue,citingPaper.abstract,"
    "citingPaper.citationCount,citingPaper.authors,citingPaper.externalIds,citingPaper.url,citingPaper.openAccessPdf"
)


def main() -> int:
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)
    seed = resolve_seed(args)
    if not seed:
        raise SystemExit("Could not resolve seed paper from --paper.")

    references, ref_errors = fetch_references(seed, args)
    citations, citation_errors = fetch_citations(seed, args)
    if args.openalex:
        oa_refs, oa_cites, oa_errors = fetch_openalex_related(seed, args)
        references = merge_related(references, oa_refs)
        citations = merge_related(citations, oa_cites)
        ref_errors.extend([e for e in oa_errors if e.startswith("references")])
        citation_errors.extend([e for e in oa_errors if e.startswith("citations")])

    predecessors = sorted(references, key=lambda r: related_score(seed, r, "reference"), reverse=True)[: args.limit]
    successors = sorted(citations, key=lambda r: related_score(seed, r, "citation"), reverse=True)[: args.limit]
    deep_citations = [r for r in successors if is_deep_citation(r)]
    if len(deep_citations) < min(5, len(successors)):
        deep_citations = successors[: min(args.limit, 10)]

    author_updates = fetch_author_updates(seed, predecessors, deep_citations, args)

    payload = {
        "seed": seed,
        "predecessors": predecessors,
        "successors": successors,
        "deep_citations": deep_citations,
        "author_updates": author_updates,
        "errors": {"references": ref_errors, "citations": citation_errors},
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    write_json(os.path.join(args.output_dir, "paper_trace.json"), payload)
    write_csv(os.path.join(args.output_dir, "paper_trace.csv"), payload)
    write_report(os.path.join(args.output_dir, "paper_trace_report.md"), payload, args)
    print(f"Wrote paper trace outputs to {args.output_dir}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Trace a seed paper's citation neighborhood.")
    parser.add_argument("--paper", required=True, help="Seed paper DOI, arXiv ID/URL, Semantic Scholar ID, title, or title substring.")
    parser.add_argument("--papers-json", default="", help="Optional papers.json corpus for local seed lookup.")
    parser.add_argument("--output-dir", default="", help="Output directory. Defaults to outputs/paper-trace-<seed>.")
    parser.add_argument("--limit", type=int, default=30, help="Maximum items per related-paper category.")
    parser.add_argument("--author-limit", type=int, default=8, help="Maximum authors to trace.")
    parser.add_argument("--author-paper-limit", type=int, default=8, help="Maximum latest papers per traced author.")
    parser.add_argument("--recent-years", type=int, default=5, help="Recent window for author update summaries.")
    parser.add_argument("--semantic-scholar-api-key", default="", help="Optional Semantic Scholar API key.")
    parser.add_argument("--openalex", action="store_true", help="Use OpenAlex as a fallback/supplement for references and citations.")
    parser.add_argument("--email", default="", help="Contact email for polite OpenAlex use.")
    parser.add_argument("--delay", type=float, default=0.25, help="Delay between API calls.")
    args = parser.parse_args()
    if not args.output_dir:
        args.output_dir = os.path.join(os.getcwd(), "outputs", "paper-trace-" + safe_filename(args.paper))
    return args


def resolve_seed(args: argparse.Namespace) -> Dict[str, Any]:
    local = resolve_seed_from_local(args.paper, args.papers_json)
    identifier = semantic_scholar_identifier(local or {"title": args.paper, "doi": "", "arxiv_id": "", "url": args.paper})
    candidates = [identifier] if identifier else []
    if not candidates:
        candidates = [args.paper]

    for candidate in candidates:
        try:
            data = s2_json(f"https://api.semanticscholar.org/graph/v1/paper/{urllib.parse.quote(candidate, safe=':')}", {"fields": S2_FIELDS}, args)
            seed = normalize_s2_paper(data)
            if candidate.lower().startswith("arxiv:") and not arxiv_resolution_matches(candidate, seed):
                continue
            if local:
                seed.update({k: v for k, v in local.items() if v and not seed.get(k)})
            return seed
        except Exception:
            continue

    search_query = (local or {}).get("title") or args.paper
    try:
        data = s2_json("https://api.semanticscholar.org/graph/v1/paper/search", {"query": search_query, "limit": "1", "fields": S2_FIELDS}, args)
        rows = data.get("data") or []
        if rows:
            return normalize_s2_paper(rows[0])
    except Exception:
        pass
    return local or {}


def arxiv_resolution_matches(identifier: str, seed: Dict[str, Any]) -> bool:
    expected = strip_arxiv_version(identifier.split(":", 1)[1])
    actual = strip_arxiv_version(seed.get("arxiv_id", ""))
    if actual and actual == expected:
        return True
    title = (seed.get("title") or "").strip().lower()
    return bool(title and title != "arxiv" and expected in json.dumps(seed.get("externalIds", {}), ensure_ascii=False).lower())


def resolve_seed_from_local(paper: str, path: str) -> Dict[str, Any]:
    if not path or not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        records = json.load(f)
    needle = paper.lower()
    for record in records:
        haystack = " ".join(str(record.get(k, "")) for k in ("title", "doi", "arxiv_id", "url", "open_access_url")).lower()
        if needle in haystack:
            return normalize_local_record(record)
    return {}


def semantic_scholar_identifier(record: Dict[str, Any]) -> str:
    arxiv_id = infer_arxiv_id(record)
    if arxiv_id:
        return "ARXIV:" + strip_arxiv_version(arxiv_id)
    doi = clean_doi(record.get("doi", ""))
    if doi:
        return "DOI:" + doi
    value = str(record.get("url") or record.get("title") or "")
    match = re.search(r"semanticscholar\.org/paper/([A-Za-z0-9]+)", value)
    if match:
        return match.group(1)
    return ""


def fetch_references(seed: Dict[str, Any], args: argparse.Namespace) -> Tuple[List[Dict[str, Any]], List[str]]:
    paper_id = seed.get("paperId") or semantic_scholar_identifier(seed)
    if not paper_id:
        return [], ["references: seed has no Semantic Scholar identifier"]
    paper_id = urllib.parse.quote(str(paper_id), safe=":")
    return fetch_s2_related(f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}/references", "reference", args)


def fetch_citations(seed: Dict[str, Any], args: argparse.Namespace) -> Tuple[List[Dict[str, Any]], List[str]]:
    paper_id = seed.get("paperId") or semantic_scholar_identifier(seed)
    if not paper_id:
        return [], ["citations: seed has no Semantic Scholar identifier"]
    paper_id = urllib.parse.quote(str(paper_id), safe=":")
    return fetch_s2_related(f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}/citations", "citation", args)


def fetch_s2_related(url: str, relation: str, args: argparse.Namespace) -> Tuple[List[Dict[str, Any]], List[str]]:
    rows: List[Dict[str, Any]] = []
    errors: List[str] = []
    offset = 0
    page_size = min(100, max(1, args.limit))
    while len(rows) < args.limit:
        try:
            fields = S2_REFERENCE_FIELDS if relation == "reference" else S2_CITATION_FIELDS
            data = s2_json(url, {"fields": fields, "limit": str(page_size), "offset": str(offset)}, args)
        except Exception as exc:
            errors.append(f"{relation}: {type(exc).__name__}: {exc}")
            break
        page = data.get("data")
        if page is None:
            errors.append(f"{relation}: unavailable or elided by source")
            break
        for item in page:
            paper = item.get("citedPaper") if relation == "reference" else item.get("citingPaper")
            if not paper:
                continue
            rows.append(normalize_related(paper, relation, item, "semanticscholar"))
            if len(rows) >= args.limit:
                break
        next_offset = data.get("next")
        if next_offset is None or not page:
            break
        offset = int(next_offset)
        time.sleep(args.delay)
    return rows, errors


def fetch_openalex_related(seed: Dict[str, Any], args: argparse.Namespace) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
    errors: List[str] = []
    try:
        work = resolve_openalex_work(seed, args)
    except Exception as exc:
        return [], [], [f"openalex: {type(exc).__name__}: {exc}"]
    if not work:
        return [], [], ["openalex: seed work not resolved"]

    refs: List[Dict[str, Any]] = []
    for work_id in (work.get("referenced_works") or [])[: args.limit]:
        try:
            ref_work = http_json(openalex_api_url(work_id))
            refs.append(normalize_openalex_work(ref_work, "reference"))
            time.sleep(args.delay)
        except Exception as exc:
            errors.append(f"references/openalex: {type(exc).__name__}: {exc}")

    cites: List[Dict[str, Any]] = []
    cited_by_url = work.get("cited_by_api_url")
    if cited_by_url:
        sep = "&" if "?" in cited_by_url else "?"
        url = f"{cited_by_url}{sep}per-page={min(args.limit, 100)}"
        if args.email:
            url += "&mailto=" + urllib.parse.quote(args.email)
        try:
            data = http_json(url)
            for item in data.get("results", [])[: args.limit]:
                cites.append(normalize_openalex_work(item, "citation"))
        except Exception as exc:
            errors.append(f"citations/openalex: {type(exc).__name__}: {exc}")
    return refs, cites, errors


def openalex_api_url(work_id: str) -> str:
    work_id = str(work_id or "")
    match = re.search(r"/(W\d+)$", work_id)
    if match:
        return "https://api.openalex.org/works/" + match.group(1)
    if work_id.startswith("W"):
        return "https://api.openalex.org/works/" + work_id
    return work_id


def resolve_openalex_work(seed: Dict[str, Any], args: argparse.Namespace) -> Dict[str, Any]:
    doi = clean_doi(seed.get("doi", ""))
    if doi:
        url = "https://api.openalex.org/works/https://doi.org/" + urllib.parse.quote(doi, safe="/")
        if args.email:
            url += "?mailto=" + urllib.parse.quote(args.email)
        return http_json(url)
    title = seed.get("title")
    if title:
        params = {"search": title, "per-page": "1"}
        if args.email:
            params["mailto"] = args.email
        data = http_json("https://api.openalex.org/works?" + urllib.parse.urlencode(params))
        rows = data.get("results") or []
        return rows[0] if rows else {}
    return {}


def fetch_author_updates(seed: Dict[str, Any], predecessors: List[Dict[str, Any]], deep_citations: List[Dict[str, Any]], args: argparse.Namespace) -> List[Dict[str, Any]]:
    author_evidence = collect_author_evidence(seed, predecessors, deep_citations)
    resolved_authors, skipped_authors = resolve_author_evidences(author_evidence, args)
    author_ids = resolved_authors[: args.author_limit]

    seed_year = seed.get("year") or 0
    recent_floor = dt.datetime.now().year - args.recent_years
    topic_text = build_trace_topic_text(seed, predecessors, deep_citations)
    updates = []
    for author_id, name, role, confidence, note in author_ids:
        try:
            data = s2_json(f"https://api.semanticscholar.org/graph/v1/author/{author_id}/papers", {
                "fields": "paperId,title,year,venue,abstract,citationCount,externalIds,url",
                "limit": "100",
            }, args)
            papers = [normalize_s2_paper(p) for p in data.get("data", [])]
            after_seed = [p for p in papers if (p.get("year") or 0) > seed_year]
            recent = [p for p in papers if (p.get("year") or 0) >= recent_floor]
            ranked, selection_note = rank_author_latest_papers(papers, seed, topic_text, seed_year, recent_floor)
            updates.append({
                "authorId": author_id,
                "name": name,
                "role": role,
                "resolution_confidence": confidence,
                "resolution_note": note,
                "selection_note": selection_note,
                "broad_recent_count": len(after_seed or recent or papers),
                "latest_papers": ranked[: args.author_paper_limit],
            })
            time.sleep(args.delay)
        except Exception as exc:
            updates.append({
                "authorId": author_id,
                "name": name,
                "role": role,
                "resolution_confidence": confidence,
                "resolution_note": note,
                "error": f"{type(exc).__name__}: {exc}",
                "latest_papers": [],
            })
    remaining_skip_slots = max(0, args.author_limit - len(updates))
    for skipped in skipped_authors[:remaining_skip_slots]:
        updates.append({
            "name": skipped.get("name", ""),
            "role": skipped.get("role", ""),
            "skipped": True,
            "resolution_note": skipped.get("reason", ""),
            "latest_papers": [],
        })
    return updates


def s2_json(url: str, params: Dict[str, str], args: argparse.Namespace) -> Dict[str, Any]:
    full_url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    headers = {"User-Agent": "scholarly-deep-research-skill/1.0"}
    if args.semantic_scholar_api_key:
        headers["x-api-key"] = args.semantic_scholar_api_key
    return http_json(full_url, headers=headers)


def http_json(url: str, headers: Optional[Dict[str, str]] = None, retries: int = 2) -> Dict[str, Any]:
    request = urllib.request.Request(url, headers=headers or {"User-Agent": "scholarly-deep-research-skill/1.0"})
    last_error: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=35) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
    raise RuntimeError(last_error)


def normalize_s2_paper(item: Dict[str, Any]) -> Dict[str, Any]:
    external = item.get("externalIds") or {}
    return {
        "paperId": item.get("paperId", ""),
        "title": item.get("title", ""),
        "authors": item.get("authors") or [],
        "year": item.get("year"),
        "venue": item.get("venue", ""),
        "abstract": item.get("abstract") or "",
        "citationCount": item.get("citationCount") or 0,
        "referenceCount": item.get("referenceCount") or 0,
        "doi": clean_doi(external.get("DOI", "")),
        "arxiv_id": clean_arxiv_id(external.get("ArXiv", "")),
        "externalIds": external,
        "url": item.get("url", ""),
        "openAccessPdf": item.get("openAccessPdf") or {},
        "fieldsOfStudy": item.get("fieldsOfStudy") or [],
        "publicationTypes": item.get("publicationTypes") or [],
    }


def normalize_local_record(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "paperId": item.get("paperId", ""),
        "title": item.get("title", ""),
        "authors": [{"name": a} if isinstance(a, str) else a for a in item.get("authors", [])],
        "year": item.get("year"),
        "venue": item.get("venue", ""),
        "abstract": item.get("abstract", ""),
        "citationCount": item.get("citation_count") or item.get("citationCount") or 0,
        "doi": clean_doi(item.get("doi", "")),
        "arxiv_id": clean_arxiv_id(item.get("arxiv_id", "")),
        "url": item.get("url", ""),
        "openAccessPdf": {"url": item.get("open_access_url", "")} if item.get("open_access_url") else {},
    }


def normalize_related(paper: Dict[str, Any], relation: str, item: Dict[str, Any], source: str) -> Dict[str, Any]:
    row = normalize_s2_paper(paper)
    row.update({
        "relation": relation,
        "source": source,
        "contexts": item.get("contexts") or [],
        "intents": item.get("intents") or [],
        "isInfluential": bool(item.get("isInfluential")),
    })
    return row


def normalize_openalex_work(item: Dict[str, Any], relation: str) -> Dict[str, Any]:
    authors = []
    for authorship in item.get("authorships", []):
        author = authorship.get("author") or {}
        if author.get("display_name"):
            authors.append({"name": author["display_name"], "authorId": author.get("id", "")})
    return {
        "paperId": item.get("id", ""),
        "title": item.get("title", ""),
        "authors": authors,
        "year": item.get("publication_year"),
        "venue": ((item.get("primary_location") or {}).get("source") or {}).get("display_name", ""),
        "abstract": "",
        "citationCount": item.get("cited_by_count") or 0,
        "referenceCount": len(item.get("referenced_works") or []),
        "doi": clean_doi(item.get("doi", "")),
        "arxiv_id": "",
        "url": item.get("doi") or item.get("id", ""),
        "relation": relation,
        "source": "openalex",
        "contexts": [],
        "intents": [],
        "isInfluential": False,
    }


def merge_related(primary: List[Dict[str, Any]], secondary: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged = list(primary)
    seen = {paper_identity(row) for row in merged}
    for row in secondary:
        ident = paper_identity(row)
        if ident and ident not in seen:
            seen.add(ident)
            merged.append(row)
    return merged


def related_score(seed: Dict[str, Any], item: Dict[str, Any], relation: str) -> float:
    seed_terms = set(tokenize(seed.get("title", "") + " " + seed.get("abstract", "")))
    item_terms = set(tokenize(item.get("title", "") + " " + item.get("abstract", "")))
    overlap = len(seed_terms & item_terms) / max(len(seed_terms), 1)
    cites = math.log1p(item.get("citationCount") or 0) / 10.0
    intent_score = 0.0
    intents = {str(x).lower() for x in item.get("intents", [])}
    if "methodology" in intents or "method" in intents:
        intent_score += 0.25
    if "result" in intents:
        intent_score += 0.2
    if "background" in intents:
        intent_score += 0.05
    if item.get("isInfluential"):
        intent_score += 0.25
    context_score = 0.15 if citation_context_is_deep(item.get("contexts", [])) else 0.0
    year_score = 0.0
    if relation == "citation" and seed.get("year") and item.get("year"):
        year_score = max(0.0, min(0.15, (int(item["year"]) - int(seed["year"])) / 30.0))
    return round(0.35 * overlap + 0.2 * min(cites, 1.0) + intent_score + context_score + year_score, 4)


def is_deep_citation(item: Dict[str, Any]) -> bool:
    intents = {str(x).lower() for x in item.get("intents", [])}
    return bool(item.get("isInfluential") or intents & {"methodology", "method", "result"} or citation_context_is_deep(item.get("contexts", [])))


def citation_context_is_deep(contexts: Iterable[str]) -> bool:
    text = " ".join(contexts).lower()
    patterns = [
        "compare", "comparison", "baseline", "outperform", "method", "approach", "algorithm",
        "we use", "we adopt", "we extend", "build on", "based on", "following", "inspired",
        "control law", "framework", "formulation",
    ]
    return any(p in text for p in patterns)


def write_json(path: str, payload: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def write_csv(path: str, payload: Dict[str, Any]) -> None:
    fields = ["category", "title", "authors", "year", "venue", "doi", "arxiv_id", "citationCount", "score", "intents", "isInfluential", "url"]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for category in ("predecessors", "successors", "deep_citations"):
            for row in payload.get(category, []):
                writer.writerow({
                    "category": category,
                    "title": row.get("title", ""),
                    "authors": "; ".join(a.get("name", "") for a in row.get("authors", [])),
                    "year": row.get("year", ""),
                    "venue": row.get("venue", ""),
                    "doi": row.get("doi", ""),
                    "arxiv_id": row.get("arxiv_id", ""),
                    "citationCount": row.get("citationCount", 0),
                    "score": related_score(payload["seed"], row, row.get("relation", "")),
                    "intents": "; ".join(row.get("intents", [])),
                    "isInfluential": row.get("isInfluential", False),
                    "url": row.get("url", ""),
                })


def write_report(path: str, payload: Dict[str, Any], args: argparse.Namespace) -> None:
    seed = payload["seed"]
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# 以文找文报告：{seed.get('title') or args.paper}\n\n")
        f.write("## 种子论文\n\n")
        f.write(f"- Title: {seed.get('title')}\n")
        f.write(f"- Authors: {format_authors(seed.get('authors', []))}\n")
        f.write(f"- Year / Venue: {seed.get('year') or 'n.d.'} / {seed.get('venue') or 'Unknown'}\n")
        f.write(f"- DOI / arXiv: {seed.get('doi') or '-'} / {seed.get('arxiv_id') or '-'}\n")
        f.write(f"- Semantic Scholar citations / references: {seed.get('citationCount', 0)} / {seed.get('referenceCount', 0)}\n")
        f.write("\n## 如何解读本报告\n\n")
        f.write(
            "“前身/启发”基于种子论文的参考文献和元数据相似度，只能表示可能的知识来源；"
            "“后续发展”基于引用种子论文的后续论文；“方法引用/对比”优先使用 Semantic Scholar 的 citation contexts、intents 和 isInfluential 标记，"
            "没有上下文时降级为 metadata-only 线索。\n\n"
        )
        write_related_section(f, "## 1. 可能的前身与启发文献", payload.get("predecessors", []), seed, "reference")
        write_related_section(f, "## 2. 后续发展文献", payload.get("successors", []), seed, "citation")
        write_related_section(f, "## 3. 引用了本文方法或进行了较深关联的后续文献", payload.get("deep_citations", []), seed, "citation")
        f.write("## 4. 作者与相关作者的最新发展\n\n")
        for author in payload.get("author_updates", []):
            f.write(f"### {author.get('name')} ({author.get('role')})\n\n")
            if author.get("skipped"):
                f.write(f"- Skipped: {author.get('resolution_note') or 'author identity could not be resolved with sufficient confidence'}\n\n")
                continue
            if author.get("resolution_note"):
                confidence = author.get("resolution_confidence")
                suffix = f"; confidence={confidence:.2f}" if isinstance(confidence, (int, float)) else ""
                f.write(f"- Author resolution: {author.get('resolution_note')}{suffix}\n")
            if author.get("selection_note"):
                f.write(f"- Paper selection: {author.get('selection_note')}\n")
            if author.get("error"):
                f.write(f"- Error: {author['error']}\n\n")
                continue
            latest = author.get("latest_papers", [])[: args.author_paper_limit]
            if not latest:
                f.write("- 未返回可用的近期论文记录。\n")
            for paper in latest:
                f.write(f"- {paper_line(paper)}\n")
            f.write("\n")
        if payload.get("errors", {}).get("references") or payload.get("errors", {}).get("citations"):
            f.write("## 5. 数据缺口与错误\n\n")
            for kind, errors in payload.get("errors", {}).items():
                for error in errors:
                    f.write(f"- {kind}: {error}\n")
            f.write("\n")
        f.write("## 6. 可复核输出\n\n")
        f.write("- `paper_trace.json`: 完整结构化结果。\n")
        f.write("- `paper_trace.csv`: 适合表格筛选的关系论文列表。\n")
        f.write("- `paper_trace_report.md`: 本报告。\n")


def write_related_section(f: Any, title: str, rows: List[Dict[str, Any]], seed: Dict[str, Any], relation: str) -> None:
    f.write(title + "\n\n")
    if not rows:
        f.write("未获得可用结果。可能是该数据源隐藏 references/citations，或当前 API 限流。\n\n")
        return
    for i, row in enumerate(rows[:15], start=1):
        score = related_score(seed, row, relation)
        f.write(f"### {i}. {row.get('title') or 'Untitled'}\n\n")
        f.write(f"- Authors: {format_authors(row.get('authors', []))}\n")
        f.write(f"- Year / Venue: {row.get('year') or 'n.d.'} / {row.get('venue') or 'Unknown'}\n")
        f.write(f"- DOI / arXiv: {row.get('doi') or '-'} / {row.get('arxiv_id') or '-'}\n")
        f.write(f"- Citations: {row.get('citationCount', 0)}; trace score: {score}\n")
        if row.get("intents"):
            f.write(f"- Citation intents: {', '.join(row.get('intents', []))}\n")
        if row.get("isInfluential"):
            f.write("- Marked influential by Semantic Scholar.\n")
        if row.get("contexts"):
            f.write("- Citation contexts:\n")
            for context in row.get("contexts", [])[:3]:
                f.write(f"  - {compact_ws(context)[:450]}\n")
        if row.get("abstract"):
            f.write(f"- Abstract signal: {compact_ws(row.get('abstract'))[:650]}\n")
        f.write("\n")


def paper_line(paper: Dict[str, Any]) -> str:
    relevance = paper.get("trace_topic_relevance")
    relevance_note = f", topic_relevance={relevance:.2f}" if isinstance(relevance, (int, float)) else ""
    return (
        f"{paper.get('title') or 'Untitled'} ({paper.get('year') or 'n.d.'}), "
        f"{paper.get('venue') or 'Unknown'}, citations={paper.get('citationCount', 0)}, "
        f"DOI/arXiv={paper.get('doi') or paper.get('arxiv_id') or '-'}{relevance_note}."
    )


def format_authors(authors: List[Dict[str, Any]]) -> str:
    names = [a.get("name", "") for a in authors if a.get("name")]
    if len(names) > 5:
        return ", ".join(names[:5]) + ", et al."
    return ", ".join(names) or "Unknown"


def build_trace_topic_text(seed: Dict[str, Any], predecessors: List[Dict[str, Any]], deep_citations: List[Dict[str, Any]]) -> str:
    parts = [seed.get("title", "")]
    parts.extend(item.get("title", "") for item in predecessors[:8])
    parts.extend(item.get("title", "") for item in deep_citations[:8])
    return " ".join(parts)


def rank_author_latest_papers(
    papers: List[Dict[str, Any]],
    seed: Dict[str, Any],
    topic_text: str,
    seed_year: int,
    recent_floor: int,
) -> Tuple[List[Dict[str, Any]], str]:
    seed_id = paper_identity(seed)
    scored = []
    for paper in papers:
        if seed_id and paper_identity(paper) == seed_id:
            continue
        relevance, overlap, seed_overlap = topic_relevance(topic_text, seed.get("title", ""), paper)
        if overlap < 2 or (seed_overlap < 1 and overlap < 3):
            continue
        paper = dict(paper)
        paper["trace_topic_relevance"] = round(relevance, 3)
        paper["trace_topic_overlap"] = overlap
        paper["trace_seed_title_overlap"] = seed_overlap
        scored.append((relevance, paper.get("year") or 0, paper.get("citationCount") or 0, paper))

    after_seed = [row for row in scored if (row[3].get("year") or 0) >= seed_year]
    recent = [row for row in scored if (row[3].get("year") or 0) >= recent_floor]
    selected_rows = after_seed or recent or scored
    selected_rows = sorted(selected_rows, key=lambda row: (row[0], row[1], row[2]), reverse=True)
    if selected_rows:
        note = "ranked by topic overlap with the seed trace, then year and citations; seed paper itself is excluded"
        return [row[3] for row in selected_rows], note
    return [], "no clearly topic-related recent papers found in this author's Semantic Scholar record"


def topic_relevance(topic_text: str, seed_title: str, paper: Dict[str, Any]) -> Tuple[float, int, int]:
    topic_terms = meaningful_tokens(topic_text)
    seed_terms = meaningful_tokens(seed_title)
    paper_terms = meaningful_tokens(" ".join([
        str(paper.get("title") or ""),
        str(paper.get("venue") or ""),
    ]))
    if not topic_terms or not paper_terms:
        return 0.0, 0, 0
    overlap = len(topic_terms & paper_terms)
    seed_overlap = len(seed_terms & paper_terms)
    denominator = min(len(paper_terms), 18)
    return min(1.0, overlap / max(denominator, 1)), overlap, seed_overlap


def meaningful_tokens(value: str) -> Set[str]:
    stopwords = {
        "a", "an", "analysis", "and", "approach", "are", "as", "at", "based", "be", "by",
        "control", "for", "from", "in", "into", "is", "its", "method", "methods", "model",
        "of", "on", "optimal", "or", "our", "paper", "problem", "propose", "proposed",
        "result", "results", "show", "system", "systems", "the", "their", "this", "to",
        "using", "via", "we", "with",
    }
    return {t for t in tokenize(value) if len(t) > 2 and t not in stopwords}


def collect_author_evidence(seed: Dict[str, Any], predecessors: List[Dict[str, Any]], deep_citations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    seed_authors = seed.get("authors", [])
    for author in seed_authors:
        add_author_evidence(rows, author, "seed-author", seed.get("title", ""), seed_authors)
    for item in predecessors[:4] + deep_citations[:6]:
        authors = item.get("authors", [])
        for author in authors[:2]:
            add_author_evidence(rows, author, "related-method-author", item.get("title", ""), authors)
    return rows


def add_author_evidence(rows: List[Dict[str, Any]], author: Dict[str, Any], role: str, paper_title: str, paper_authors: List[Dict[str, Any]]) -> None:
    name = compact_ws(author.get("name", ""))
    if not name:
        return
    author_id = str(author.get("authorId")) if is_s2_author_id(author.get("authorId")) else ""
    coauthors = {
        compact_ws(a.get("name", ""))
        for a in paper_authors
        if a.get("name") and not author_name_matches(name, a.get("name", ""))
    }

    for row in rows:
        row_id = row.get("authorId", "")
        same_id = bool(author_id and row_id and author_id == row_id)
        compatible_missing_id = bool((author_id or row_id) and not (author_id and row_id) and author_name_matches(row.get("name", ""), name))
        same_name_without_ids = bool(not author_id and not row_id and author_name_matches(row.get("name", ""), name))
        if not (same_id or compatible_missing_id or same_name_without_ids):
            continue
        if author_id and not row_id:
            row["authorId"] = author_id
        row["aliases"].add(name)
        if paper_title:
            row["evidence_titles"].add(paper_title)
        row["coauthors"].update(coauthors)
        if role == "seed-author" or row.get("role") != "seed-author":
            row["role"] = role
        return

    rows.append({
        "authorId": author_id,
        "name": name,
        "role": role,
        "aliases": {name},
        "evidence_titles": {paper_title} if paper_title else set(),
        "coauthors": coauthors,
    })


def resolve_author_evidences(evidences: List[Dict[str, Any]], args: argparse.Namespace) -> Tuple[List[Tuple[str, str, str, float, str]], List[Dict[str, str]]]:
    resolved: List[Tuple[str, str, str, float, str]] = []
    skipped: List[Dict[str, str]] = []
    seen_ids: Set[str] = set()
    for evidence in evidences:
        name = evidence.get("name", "")
        role = evidence.get("role", "")
        author_id = evidence.get("authorId", "")
        if is_s2_author_id(author_id):
            if author_id not in seen_ids:
                seen_ids.add(author_id)
                resolved.append((author_id, name, role, 1.0, "authorId inherited from seed or related-paper metadata"))
            continue

        candidate = resolve_author_by_name(evidence, args)
        if candidate:
            found_id = str(candidate.get("authorId") or "")
            if found_id and found_id not in seen_ids:
                seen_ids.add(found_id)
                resolved.append((
                    found_id,
                    candidate.get("name") or name,
                    role,
                    float(candidate.get("confidence") or 0.0),
                    candidate.get("note") or "resolved by contextual author search",
                ))
        else:
            skipped.append({
                "name": name,
                "role": role,
                "reason": "skipped because name search did not provide enough title/coauthor evidence to disambiguate this author",
            })
        time.sleep(args.delay)
    return resolved, skipped


def resolve_author_by_name(evidence: Dict[str, Any], args: argparse.Namespace) -> Dict[str, Any]:
    name = evidence.get("name", "")
    if not name:
        return {}
    try:
        try:
            data = s2_json("https://api.semanticscholar.org/graph/v1/author/search", {
                "query": name,
                "limit": "5",
                "fields": "authorId,name,paperCount,citationCount,papers.title,papers.year,papers.authors",
            }, args)
        except Exception:
            data = s2_json("https://api.semanticscholar.org/graph/v1/author/search", {
                "query": name,
                "limit": "5",
                "fields": "authorId,name,paperCount,citationCount",
            }, args)
    except Exception:
        return {}

    best: Dict[str, Any] = {}
    for candidate in data.get("data") or []:
        author_id = str(candidate.get("authorId") or "")
        if not is_s2_author_id(author_id):
            continue
        papers = candidate.get("papers") or fetch_author_papers_for_resolution(author_id, args)
        score, details = score_author_candidate(evidence, candidate, papers)
        candidate["confidence"] = round(score, 3)
        candidate["score_details"] = details
        if score > float(best.get("confidence") or -1):
            best = candidate

    if not best:
        return {}
    details = best.get("score_details") or {}
    enough_context = bool(
        details.get("exact_title")
        or details.get("max_title_similarity", 0.0) >= 0.28
        or details.get("coauthor_matches", 0) > 0
    )
    if float(best.get("confidence") or 0.0) < 3.0 or not enough_context:
        return {}
    return {
        "authorId": str(best.get("authorId") or ""),
        "name": best.get("name") or name,
        "confidence": min(float(best.get("confidence") or 0.0) / 7.5, 0.99),
        "note": (
            "resolved by Semantic Scholar author search with contextual evidence "
            f"(title_similarity={details.get('max_title_similarity', 0.0):.2f}, "
            f"coauthor_matches={details.get('coauthor_matches', 0)})"
        ),
    }


def fetch_author_papers_for_resolution(author_id: str, args: argparse.Namespace) -> List[Dict[str, Any]]:
    try:
        data = s2_json(f"https://api.semanticscholar.org/graph/v1/author/{author_id}/papers", {
            "fields": "paperId,title,year,authors",
            "limit": "30",
        }, args)
        time.sleep(args.delay)
        return data.get("data") or []
    except Exception:
        return []


def score_author_candidate(evidence: Dict[str, Any], candidate: Dict[str, Any], papers: List[Dict[str, Any]]) -> Tuple[float, Dict[str, Any]]:
    evidence_name = evidence.get("name", "")
    candidate_name = candidate.get("name", "")
    if canonical_author_name(evidence_name) == canonical_author_name(candidate_name):
        name_score = 1.5
    elif author_name_matches(evidence_name, candidate_name):
        name_score = 1.1
    else:
        name_score = 0.0

    evidence_titles = [normalize_title(t) for t in evidence.get("evidence_titles", set()) if normalize_title(t)]
    candidate_titles = [normalize_title(p.get("title", "")) for p in papers if normalize_title(p.get("title", ""))]
    max_title_similarity = 0.0
    exact_title = False
    for left in evidence_titles:
        for right in candidate_titles:
            if not left or not right:
                continue
            if left == right or (len(left) > 24 and left in right) or (len(right) > 24 and right in left):
                exact_title = True
                max_title_similarity = 1.0
                break
            max_title_similarity = max(max_title_similarity, token_similarity(left, right))
        if exact_title:
            break
    title_score = 4.0 if exact_title else 4.0 * max_title_similarity

    evidence_coauthors = {name for name in evidence.get("coauthors", set()) if name}
    matched_coauthors: Set[str] = set()
    for paper in papers:
        for author in paper.get("authors") or []:
            candidate_author_name = author.get("name", "")
            if author_name_matches(candidate_author_name, evidence_name):
                continue
            for known_name in evidence_coauthors:
                if author_name_matches(candidate_author_name, known_name):
                    matched_coauthors.add(known_name)
    coauthor_score = min(2.0, 0.75 * len(matched_coauthors))
    score = name_score + title_score + coauthor_score
    return score, {
        "name_score": name_score,
        "max_title_similarity": round(max_title_similarity, 3),
        "exact_title": exact_title,
        "coauthor_matches": len(matched_coauthors),
    }


def author_name_matches(left: str, right: str) -> bool:
    left_tokens = author_name_tokens(left)
    right_tokens = author_name_tokens(right)
    if not left_tokens or not right_tokens:
        return False
    if left_tokens == right_tokens:
        return True
    if left_tokens[-1] != right_tokens[-1]:
        return False
    left_first = left_tokens[0]
    right_first = right_tokens[0]
    return bool(left_first == right_first or left_first[:1] == right_first[:1])


def canonical_author_name(name: str) -> str:
    return " ".join(author_name_tokens(name))


def author_name_tokens(name: str) -> List[str]:
    return re.findall(r"[a-z]+", (name or "").lower())


def is_s2_author_id(value: Any) -> bool:
    return bool(re.fullmatch(r"\d+", str(value or "")))


def paper_identity(row: Dict[str, Any]) -> str:
    return row.get("doi") or row.get("arxiv_id") or row.get("paperId") or normalize_title(row.get("title", ""))


def clean_doi(value: Any) -> str:
    value = str(value or "").strip()
    value = re.sub(r"^https?://(dx\.)?doi\.org/", "", value, flags=re.I)
    value = value.replace("doi:", "").strip()
    return value.lower()


def clean_arxiv_id(value: Any) -> str:
    value = str(value or "").strip()
    value = re.sub(r"^arxiv:", "", value, flags=re.I)
    value = value.replace("https://arxiv.org/abs/", "").replace("https://arxiv.org/pdf/", "")
    return value.replace(".pdf", "")


def strip_arxiv_version(arxiv_id: str) -> str:
    return re.sub(r"v\d+$", "", clean_arxiv_id(arxiv_id), flags=re.I)


def infer_arxiv_id(record: Dict[str, Any]) -> str:
    for value in [record.get("arxiv_id", ""), record.get("doi", ""), record.get("url", ""), (record.get("openAccessPdf") or {}).get("url", "")]:
        text = str(value or "")
        match = re.search(r"arxiv[.:/](\d{4}\.\d{4,5}(?:v\d+)?)", text, flags=re.I)
        if match:
            return clean_arxiv_id(match.group(1))
        match = re.search(r"arxiv\.org/(?:abs|pdf)/([^?#\s/]+)", text, flags=re.I)
        if match:
            return clean_arxiv_id(match.group(1))
    return ""


def tokenize(value: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", (value or "").lower())


def token_similarity(left: str, right: str) -> float:
    stopwords = {
        "a", "an", "and", "are", "as", "at", "based", "by", "for", "from", "in", "into",
        "is", "of", "on", "or", "the", "to", "using", "with",
    }
    left_tokens = {t for t in tokenize(left) if len(t) > 2 and t not in stopwords}
    right_tokens = {t for t in tokenize(right) if len(t) > 2 and t not in stopwords}
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def normalize_title(value: str) -> str:
    return " ".join(tokenize(value))


def compact_ws(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def safe_filename(value: str, max_len: int = 100) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value or "").strip("-._")
    return (value[:max_len].strip("-._") or "paper")


if __name__ == "__main__":
    raise SystemExit(main())
