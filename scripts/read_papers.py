#!/usr/bin/env python3
"""Explicit paper reading mode: prefer arXiv LaTeX source, fallback to open PDFs."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Iterable, List, Tuple


def main() -> int:
    args = parse_args()
    with open(args.papers_json, "r", encoding="utf-8") as f:
        records = json.load(f)
    os.makedirs(args.output_dir, exist_ok=True)
    results = run_reading(records, args)
    write_manifest(os.path.join(args.output_dir, "pdf_manifest.csv"), results)
    write_index(os.path.join(args.output_dir, "reading_index.md"), results, args)
    print(f"Processed {len(results)} paper(s) into {args.output_dir}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read selected papers from papers.json.")
    parser.add_argument("--papers-json", required=True, help="Path to papers.json produced by lit_retrieve.py.")
    parser.add_argument("--query", default="", help="Research topic query for reading report context.")
    parser.add_argument("--output-dir", default="", help="Run output directory. Defaults to the papers.json directory.")
    parser.add_argument("--reading-limit", type=int, default=5, help="Maximum number of papers to read.")
    parser.add_argument(
        "--reading-selection",
        choices=("auto", "top", "high-citation", "recent", "manual"),
        default="auto",
        help="Paper selection strategy.",
    )
    parser.add_argument("--paper-ids", default="", help="Comma-separated DOI, arXiv ID, or title substrings for manual selection.")
    parser.add_argument(
        "--pdf-policy",
        choices=("open-access-only", "none"),
        default="open-access-only",
        help="PDF fallback policy.",
    )
    parser.add_argument("--skip-pdf-download", action="store_true", help="Do not download PDFs when TeX source is unavailable.")
    parser.add_argument("--max-pages", type=int, default=30, help="Maximum PDF pages to extract with pdftotext.")
    parser.add_argument("--reading-max-chars", type=int, default=70000, help="Maximum extracted characters per paper.")
    parser.add_argument(
        "--arxiv-source-cache",
        default=os.path.join(os.path.expanduser("~"), ".cache", "scholarly-deep-research", "arxiv-src"),
        help="Cache directory for arXiv source archives.",
    )
    args = parser.parse_args()
    if not args.output_dir:
        args.output_dir = os.path.dirname(os.path.abspath(args.papers_json))
    return args


def run_reading(records: List[Dict[str, Any]], args: argparse.Namespace) -> List[Dict[str, Any]]:
    selected = select_records(records, args)
    dirs = {
        "sources": os.path.join(args.output_dir, "arxiv_sources"),
        "pdfs": os.path.join(args.output_dir, "pdfs"),
        "texts": os.path.join(args.output_dir, "paper_texts"),
        "reports": os.path.join(args.output_dir, "reading_reports"),
    }
    for path in dirs.values():
        os.makedirs(path, exist_ok=True)

    results: List[Dict[str, Any]] = []
    for index, record in enumerate(selected, start=1):
        key = paper_key(record, index)
        arxiv_id = infer_arxiv_id(record)
        result = {
            "key": key,
            "title": record.get("title", ""),
            "doi": record.get("doi", ""),
            "arxiv_id": arxiv_id,
            "status": "metadata-only",
            "source_mode": "metadata",
            "pdf_url": "",
            "pdf_path": "",
            "text_path": "",
            "report_path": os.path.join(dirs["reports"], f"{key}.md"),
            "notes": [],
        }

        text_content = ""
        text_meta: Dict[str, Any] = {}

        if arxiv_id:
            source_dir, note = fetch_arxiv_source(arxiv_id, args.arxiv_source_cache, os.path.join(dirs["sources"], key))
            if note:
                result["notes"].append(note)
            if source_dir:
                text_content, text_meta = read_latex_project(source_dir, args.reading_max_chars)
                if text_content:
                    result["status"] = "read"
                    result["source_mode"] = "arxiv-latex"

        if not text_content and args.pdf_policy != "none" and not args.skip_pdf_download:
            pdf_url = select_pdf_url(record, arxiv_id)
            result["pdf_url"] = pdf_url
            if pdf_url:
                pdf_path, note = download_pdf(pdf_url, os.path.join(dirs["pdfs"], f"{key}.pdf"))
                if note:
                    result["notes"].append(note)
                if pdf_path:
                    result["pdf_path"] = pdf_path
                    pdf_text, pdf_meta = extract_pdf_text(pdf_path, os.path.join(dirs["texts"], f"{key}.txt"), args.max_pages, args.reading_max_chars)
                    if pdf_text:
                        text_content = pdf_text
                        text_meta = pdf_meta
                        result["status"] = "read"
                        result["source_mode"] = "pdf-text"
                    else:
                        result["status"] = "pdf-saved"
                        result["source_mode"] = "pdf"
                        result["notes"].append(pdf_meta.get("error", "PDF saved but text was not extracted."))
            else:
                result["notes"].append("No open-access PDF URL inferred.")
        elif not text_content:
            result["notes"].append("PDF fallback skipped by policy.")

        if text_content:
            text_path = os.path.join(dirs["texts"], f"{key}.txt")
            with open(text_path, "w", encoding="utf-8") as f:
                f.write(text_content)
            result["text_path"] = text_path
            with open(os.path.join(dirs["texts"], f"{key}.json"), "w", encoding="utf-8") as f:
                json.dump({"metadata": text_meta, "record": record, "text_path": text_path}, f, ensure_ascii=False, indent=2)

        write_reading_report(result["report_path"], record, result, text_content, text_meta, args.query)
        results.append(result)
        time.sleep(0.35)
    return results


def select_records(records: List[Dict[str, Any]], args: argparse.Namespace) -> List[Dict[str, Any]]:
    limit = max(0, args.reading_limit)
    if args.reading_selection == "manual":
        needles = [n.strip().lower() for n in args.paper_ids.split(",") if n.strip()]
        selected = []
        for record in records:
            haystack = " ".join([record.get("title", ""), record.get("doi", ""), infer_arxiv_id(record)]).lower()
            if any(needle in haystack for needle in needles):
                selected.append(record)
        return (selected or records)[:limit]
    if args.reading_selection == "high-citation":
        return sorted(records, key=lambda r: (r.get("citation_count", 0), r.get("score", 0)), reverse=True)[:limit]
    if args.reading_selection == "recent":
        return sorted(records, key=lambda r: (r.get("year") or 0, r.get("score", 0)), reverse=True)[:limit]
    if args.reading_selection == "top":
        return records[:limit]

    selected: List[Dict[str, Any]] = []
    seen = set()
    pools = [
        sorted(records, key=lambda r: (r.get("citation_count", 0), r.get("score", 0)), reverse=True),
        records,
        sorted(records, key=lambda r: (r.get("year") or 0, r.get("score", 0)), reverse=True),
    ]
    for pool in pools:
        for record in pool:
            key = normalize_title(record.get("title", "")) or record.get("doi", "") or infer_arxiv_id(record)
            if key and key not in seen:
                seen.add(key)
                selected.append(record)
            if len(selected) >= limit:
                return selected
    return selected


def fetch_arxiv_source(arxiv_id: str, cache_dir: str, output_dir: str) -> Tuple[str, str]:
    os.makedirs(cache_dir, exist_ok=True)
    archive_path = os.path.join(cache_dir, f"{safe_filename(strip_arxiv_version(arxiv_id))}.tar.gz")
    last_error = ""
    for candidate in dedupe_strings([arxiv_id, strip_arxiv_version(arxiv_id)]):
        url = f"https://arxiv.org/src/{candidate}"
        try:
            if not os.path.exists(archive_path) or os.path.getsize(archive_path) == 0:
                data = http_bytes(url)
                with open(archive_path, "wb") as f:
                    f.write(data)
            if os.path.exists(output_dir):
                shutil.rmtree(output_dir)
            os.makedirs(output_dir, exist_ok=True)
            if extract_source_archive(archive_path, output_dir):
                return output_dir, f"arXiv source fetched from {url}"
        except Exception as exc:
            last_error = f"arXiv source unavailable from {url}: {type(exc).__name__}: {exc}"
            if os.path.exists(archive_path) and os.path.getsize(archive_path) == 0:
                os.remove(archive_path)
    return "", last_error or "arXiv source unavailable."


def extract_source_archive(archive_path: str, output_dir: str) -> bool:
    try:
        with tarfile.open(archive_path, "r:*") as tar:
            safe_extract_tar(tar, output_dir)
        return True
    except tarfile.TarError:
        pass
    try:
        with gzip.open(archive_path, "rb") as src, open(os.path.join(output_dir, "source.tex"), "wb") as dst:
            shutil.copyfileobj(src, dst)
        return True
    except Exception:
        return False


def safe_extract_tar(tar: tarfile.TarFile, path: str) -> None:
    root = os.path.abspath(path)
    for member in tar.getmembers():
        target = os.path.abspath(os.path.join(path, member.name))
        if not target.startswith(root):
            raise RuntimeError(f"Unsafe path in archive: {member.name}")
    try:
        tar.extractall(path, filter="data")
    except TypeError:
        tar.extractall(path)


def read_latex_project(source_dir: str, max_chars: int) -> Tuple[str, Dict[str, Any]]:
    tex_files = find_tex_files(source_dir)
    if not tex_files:
        return "", {"error": "No .tex files found."}
    entrypoint = choose_entrypoint(tex_files)
    visited: set[str] = set()
    chunks: List[str] = []
    read_latex_file(entrypoint, visited, chunks, max_chars)
    raw = "\n\n".join(chunks)
    if not raw:
        return "", {"entrypoint": entrypoint, "files_read": []}
    body = latex_document_body(raw)
    return clean_latex(body)[:max_chars], {
        "entrypoint": entrypoint,
        "files_read": sorted(visited),
        "file_count": len(visited),
        "abstract": extract_latex_environment(body, "abstract"),
        "sections": extract_section_titles(body)[:40],
    }


def find_tex_files(source_dir: str) -> List[str]:
    paths = []
    for root, _, files in os.walk(source_dir):
        for name in files:
            if name.lower().endswith(".tex"):
                paths.append(os.path.join(root, name))
    return paths


def choose_entrypoint(tex_files: List[str]) -> str:
    preferred = ("main.tex", "paper.tex", "article.tex", "ms.tex", "manuscript.tex", "source.tex")
    by_name = {os.path.basename(path).lower(): path for path in tex_files}
    for name in preferred:
        if name in by_name:
            return by_name[name]
    scored = []
    for path in tex_files:
        content = read_text(path, 20000)
        score = int("\\documentclass" in content) * 10 + int("\\begin{document}" in content) * 10 + int("\\title" in content) * 2
        score += min(os.path.getsize(path) // 5000, 5)
        scored.append((score, path))
    return sorted(scored, reverse=True)[0][1]


def read_latex_file(path: str, visited: set[str], chunks: List[str], max_chars: int) -> None:
    norm = os.path.abspath(path)
    if norm in visited or sum(len(c) for c in chunks) > max_chars:
        return
    visited.add(norm)
    content = read_text(norm, max_chars)
    chunks.append(f"\n% FILE: {norm}\n{content}")
    base_dir = os.path.dirname(norm)
    for include in re.findall(r"\\(?:input|include|subfile)\{([^}]+)\}", content):
        include = include.strip()
        if not include or include.startswith("\\"):
            continue
        include_path = include if include.lower().endswith(".tex") else include + ".tex"
        candidate = os.path.abspath(os.path.join(base_dir, include_path))
        if os.path.exists(candidate):
            read_latex_file(candidate, visited, chunks, max_chars)


def read_text(path: str, max_chars: int) -> str:
    for encoding in ("utf-8", "latin-1"):
        try:
            with open(path, "r", encoding=encoding) as f:
                return f.read(max_chars)
        except UnicodeDecodeError:
            continue
    return ""


def clean_latex(value: str) -> str:
    value = re.sub(r"\\(?:usepackage|documentclass)(\[[^\]]*\])?\{[^}]*\}", " ", value)
    value = re.sub(r"\\(?:newcommand|renewcommand|def|DeclareMathOperator)\s*\\?[A-Za-z@]+\s*(\[[^\]]*\])?(\{[^{}]*\}){0,3}", " ", value)
    value = re.sub(r"\\(?:author|affiliation|thanks)\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", " ", value)
    value = re.sub(r"(?<!\\)%.*", "", value)
    value = re.sub(r"\\(cite|citet|citep|ref|eqref|label)\*?(\[[^\]]*\])?\{[^}]*\}", "", value)
    value = re.sub(r"\\(section|subsection|subsubsection|paragraph)\*?\{([^}]*)\}", r"\n\n## \2\n\n", value)
    value = re.sub(r"\\(title|caption|textbf|emph|textit)\{([^}]*)\}", r"\2", value)
    value = re.sub(r"\\begin\{([^}]+)\}", r"\n[\1]\n", value)
    value = re.sub(r"\\end\{[^}]+\}", "\n", value)
    value = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?", " ", value)
    return re.sub(r"\s+", " ", value.replace("~", " ")).strip()


def latex_document_body(value: str) -> str:
    match = re.search(r"\\begin\{document\}", value)
    if match:
        return value[match.end():]
    return value


def extract_latex_environment(value: str, env: str) -> str:
    match = re.search(rf"\\begin\{{{re.escape(env)}\}}(.*?)\\end\{{{re.escape(env)}\}}", value, flags=re.S)
    return clean_latex(match.group(1))[:3000] if match else ""


def extract_section_titles(value: str) -> List[str]:
    return [compact_ws(match.group(2)) for match in re.finditer(r"\\(section|subsection|subsubsection)\*?\{([^}]*)\}", value)]


def select_pdf_url(record: Dict[str, Any], arxiv_id: str = "") -> str:
    if arxiv_id:
        return f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    for key in ("open_access_url", "url"):
        url = str(record.get(key) or "")
        if "arxiv.org/pdf/" in url.lower() or url.lower().endswith(".pdf"):
            return url
    return ""


def download_pdf(url: str, path: str) -> Tuple[str, str]:
    try:
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            data = http_bytes(url)
            if not data.startswith(b"%PDF"):
                return "", f"URL did not return a PDF header: {url}"
            with open(path, "wb") as f:
                f.write(data)
        return path, f"PDF saved from {url}"
    except Exception as exc:
        return "", f"PDF download failed from {url}: {type(exc).__name__}: {exc}"


def extract_pdf_text(pdf_path: str, text_path: str, max_pages: int, max_chars: int) -> Tuple[str, Dict[str, Any]]:
    pdftotext = shutil.which("pdftotext")
    if not pdftotext:
        return "", {"error": "pdftotext not found on PATH."}
    cmd = [pdftotext, "-f", "1", "-l", str(max_pages), "-layout", pdf_path, text_path]
    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if completed.returncode != 0:
            return "", {"error": completed.stderr.strip() or "pdftotext failed."}
        with open(text_path, "r", encoding="utf-8", errors="replace") as f:
            return compact_ws(f.read(max_chars)), {"extractor": "pdftotext", "max_pages": max_pages}
    except Exception as exc:
        return "", {"error": f"{type(exc).__name__}: {exc}"}


def write_reading_report(path: str, record: Dict[str, Any], result: Dict[str, Any], text: str, meta: Dict[str, Any], query: str) -> None:
    snippets = reading_snippets(text)
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# Paper Reading Report: {record.get('title') or 'Untitled'}\n\n")
        f.write("## Metadata\n\n")
        f.write(f"- Authors: {', '.join(record.get('authors') or []) or 'Unknown'}\n")
        f.write(f"- Year: {record.get('year') or 'n.d.'}\n")
        f.write(f"- Venue: {record.get('venue') or 'Unknown'}\n")
        f.write(f"- DOI: {record.get('doi') or 'None'}\n")
        f.write(f"- arXiv ID: {result.get('arxiv_id') or 'None'}\n")
        f.write(f"- Source mode: {result.get('source_mode')}\n")
        f.write(f"- Reading status: {result.get('status')}\n")
        if result.get("pdf_url"):
            f.write(f"- PDF URL: {result['pdf_url']}\n")
        if result.get("pdf_path"):
            f.write(f"- Local PDF: {result['pdf_path']}\n")
        if result.get("text_path"):
            f.write(f"- Extracted text: {result['text_path']}\n")
        if meta.get("entrypoint"):
            f.write(f"- LaTeX entrypoint: {meta.get('entrypoint')}\n")
            f.write(f"- LaTeX files read: {meta.get('file_count', 0)}\n")
        if result.get("notes"):
            f.write(f"- Notes: {'; '.join(result['notes'])}\n")
        f.write("\n## Why This Paper Matters\n\n")
        f.write(f"Selected for `{query or 'the current research topic'}`. Suggested role: {paper_role(record)}.\n\n")
        for heading, key in [
            ("Research Question", "problem"),
            ("Method", "method"),
            ("Key Assumptions", "assumptions"),
            ("Theoretical Guarantees", "theory"),
            ("Experiments / Simulations", "experiments"),
            ("Limitations", "limitations"),
        ]:
            f.write(f"## {heading}\n\n")
            f.write(snippets.get(key) or fallback_text(record, key))
            f.write("\n\n")
        f.write("## Useful Evidence Snippets\n\n")
        for item in snippets.get("evidence", []) or ["No full-text snippets available; inspect the saved PDF/metadata manually."]:
            f.write(f"- {item}\n")


def reading_snippets(text: str) -> Dict[str, Any]:
    if not text:
        return {}
    lowered = text.lower()
    groups = {
        "problem": ["problem", "challenge", "objective", "we consider", "we study", "this paper"],
        "method": ["method", "approach", "algorithm", "control law", "controller", "protocol"],
        "assumptions": ["assumption", "suppose", "we assume"],
        "theory": ["theorem", "lemma", "proposition", "guarantee", "stability", "converge"],
        "experiments": ["experiment", "simulation", "numerical", "case study", "results"],
        "limitations": ["limitation", "future work", "however", "restrict"],
    }
    result: Dict[str, Any] = {}
    for key, terms in groups.items():
        result[key] = first_window(text, lowered, terms)
    result["evidence"] = split_sentences(text)[:6]
    return result


def first_window(original: str, lowered: str, terms: List[str], radius: int = 800) -> str:
    positions = [lowered.find(term) for term in terms if lowered.find(term) >= 0]
    if not positions:
        return ""
    pos = min(positions)
    return compact_ws(original[max(0, pos - radius // 3): min(len(original), pos + radius)])


def split_sentences(value: str) -> List[str]:
    parts = re.split(r"(?<=[.!?])\s+", compact_ws(value))
    return [p[:500] for p in parts if len(p) > 80]


def fallback_text(record: Dict[str, Any], key: str) -> str:
    if key == "problem" and record.get("abstract"):
        return record["abstract"][:900]
    return "Not reliably extracted by the deterministic reader; use the saved source/PDF for manual review."


def write_manifest(path: str, results: List[Dict[str, Any]]) -> None:
    fields = ["key", "title", "doi", "arxiv_id", "status", "source_mode", "pdf_url", "pdf_path", "text_path", "report_path", "notes"]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for result in results:
            row = dict(result)
            row["notes"] = "; ".join(result.get("notes") or [])
            writer.writerow(row)


def write_index(path: str, results: List[Dict[str, Any]], args: argparse.Namespace) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write("# Paper Reading Index\n\n")
        f.write(f"- Query: {args.query or 'not specified'}\n")
        f.write(f"- Selection: {args.reading_selection}\n")
        f.write(f"- Papers processed: {len(results)}\n\n")
        f.write("| Paper | Status | Mode | Report | PDF |\n")
        f.write("| --- | --- | --- | --- | --- |\n")
        for result in results:
            f.write(f"| {safe_cell(result.get('title'))} | {result.get('status')} | {result.get('source_mode')} | {safe_cell(result.get('report_path'))} | {safe_cell(result.get('pdf_path') or result.get('pdf_url'))} |\n")
        f.write("\nOnly the papers listed here were processed in reading mode; other papers remain metadata/abstract screened.\n")


def http_bytes(url: str, retries: int = 2) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "scholarly-deep-research-skill/1.0"})
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read()
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
    raise RuntimeError(last_error)


def infer_arxiv_id(record: Dict[str, Any]) -> str:
    for value in [record.get("arxiv_id", ""), record.get("doi", ""), record.get("url", ""), record.get("open_access_url", "")]:
        text = str(value or "")
        if not text:
            continue
        match = re.search(r"arxiv[.:/](\d{4}\.\d{4,5}(?:v\d+)?)", text, flags=re.I)
        if match:
            return clean_arxiv_id(match.group(1))
        match = re.search(r"arxiv\.org/(?:abs|pdf)/([^?#\s/]+)", text, flags=re.I)
        if match:
            return clean_arxiv_id(match.group(1).replace(".pdf", ""))
    return ""


def strip_arxiv_version(arxiv_id: str) -> str:
    return re.sub(r"v\d+$", "", clean_arxiv_id(arxiv_id), flags=re.I)


def clean_arxiv_id(value: Any) -> str:
    value = str(value or "").strip()
    value = re.sub(r"^arxiv:", "", value, flags=re.I)
    value = value.replace("https://arxiv.org/abs/", "").replace("https://arxiv.org/pdf/", "")
    return value.replace(".pdf", "")


def paper_key(record: Dict[str, Any], index: int = 0) -> str:
    arxiv_id = infer_arxiv_id(record)
    if arxiv_id:
        return safe_filename(f"arxiv-{strip_arxiv_version(arxiv_id)}")
    doi = record.get("doi") or ""
    if doi:
        return safe_filename("doi-" + doi.replace("/", "-"))
    tokens = tokenize(record.get("title", ""))[:8]
    return safe_filename("-".join(tokens) or f"paper-{index}")


def paper_role(record: Dict[str, Any]) -> str:
    text = " ".join([record.get("title", ""), record.get("abstract", ""), record.get("venue", "")]).lower()
    if "survey" in text or "review" in text:
        return "survey/background"
    if record.get("citation_count", 0) >= 100:
        return "foundational/high-citation"
    if "event" in text:
        return "event-triggered method"
    if "collision" in text or "obstacle" in text:
        return "safety/constraint method"
    if "algebraic" in text or "laplacian" in text or "fiedler" in text:
        return "connectivity metric method"
    return "representative related work"


def normalize_title(value: str) -> str:
    return " ".join(tokenize(value))


def tokenize(value: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", (value or "").lower())


def compact_ws(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def safe_filename(value: str, max_len: int = 110) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value or "").strip("-._")
    return (value[:max_len].strip("-._") or "paper")


def safe_cell(value: Any) -> str:
    return compact_ws(value).replace("|", "\\|")


def dedupe_strings(values: Iterable[str]) -> List[str]:
    seen = set()
    result = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
