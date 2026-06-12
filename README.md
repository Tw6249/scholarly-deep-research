# Scholarly Deep Research

**Scholarly Deep Research** is a Codex skill for reproducible academic literature retrieval and research-style topic synthesis. It combines official scholarly APIs with a documented web-supplement workflow, producing normalized evidence files, Chinese topic briefs, and Deep Research-style reports.

**Scholarly Deep Research** 是一个面向 Codex 的学术研究技能，用于可复现地检索论文、整理证据，并生成类似 Deep Research 的主题调研报告。它以官方学术 API 为主线，网页搜索作为补充，输出结构化元数据、中文主题简报和综合调研报告。

## Features

- Retrieves scholarly metadata from OpenAlex, Semantic Scholar, Crossref, PubMed, arXiv, and credential-gated IEEE Xplore.
- Normalizes papers into CSV, JSON, and BibTeX.
- Deduplicates by DOI, arXiv ID, title similarity, and title-author-year signals.
- Ranks papers with a transparent scoring formula.
- Generates Chinese `topic_brief.md` by default.
- Documents a hybrid workflow for Codex-authored `web_supplement.md` and `deep_research_report.md`.
- Adds explicit paper reading mode for arXiv LaTeX sources and open-access PDFs.
- Adds paper trace mode for seed-paper predecessors, successors, deep citations, and author trajectories.
- Avoids Google Scholar scraping, ResearchGate scraping, publisher scraping, and paywall bypassing.

## 功能

- 支持 OpenAlex、Semantic Scholar、Crossref、PubMed、arXiv，以及需要 API key 的 IEEE Xplore。
- 将论文元数据归一化为 CSV、JSON、BibTeX。
- 按 DOI、arXiv ID、标题相似度、标题-作者-年份信号去重。
- 使用透明评分公式对论文排序。
- 默认生成中文 `topic_brief.md`。
- 提供混合式工作流，让 Codex 基于网页补充生成 `web_supplement.md` 和 `deep_research_report.md`。
- 提供显式论文阅读模式，优先读取 arXiv LaTeX source，其次读取开放获取 PDF。
- 提供以文找文模式，追踪种子论文的前身、后续发展、深度引用和作者轨迹。
- 不爬取 Google Scholar、ResearchGate、出版社页面，也不绕过付费墙。

## Installation

Copy this folder into your Codex skills directory:

```powershell
Copy-Item -Recurse . "$env:USERPROFILE\.codex\skills\scholarly-deep-research"
```

Then invoke it in Codex with:

```text
Use $scholarly-deep-research to retrieve scholarly evidence and write a deep research briefing.
```

## 安装

将本目录复制到 Codex skills 目录：

```powershell
Copy-Item -Recurse . "$env:USERPROFILE\.codex\skills\scholarly-deep-research"
```

之后可以在 Codex 中这样调用：

```text
Use $scholarly-deep-research to retrieve scholarly evidence and write a deep research briefing.
```

## CLI Usage

Run the bundled Python script from the skill folder:

```powershell
python scripts\lit_retrieve.py `
  --query "multi agent connectivity control" `
  --from-year 2010 `
  --to-year 2026 `
  --limit 50 `
  --sources openalex,crossref,arxiv,pubmed,ieee `
  --report-language zh `
  --report-style brief `
  --output-dir outputs\multi-agent-connectivity-control
```

IEEE Xplore is skipped unless `--ieee-api-key` is provided. PubMed accepts optional `--ncbi-api-key`; Semantic Scholar accepts optional `--semantic-scholar-api-key`.

## 命令行用法

在 skill 目录下运行：

```powershell
python scripts\lit_retrieve.py `
  --query "multi agent connectivity control" `
  --from-year 2010 `
  --to-year 2026 `
  --limit 50 `
  --sources openalex,crossref,arxiv,pubmed,ieee `
  --report-language zh `
  --report-style brief `
  --output-dir outputs\multi-agent-connectivity-control
```

如果没有提供 `--ieee-api-key`，IEEE Xplore 会被跳过并写入日志。PubMed 可选 `--ncbi-api-key`，Semantic Scholar 可选 `--semantic-scholar-api-key`。

## Explicit Paper Reading Mode

Paper reading is intentionally a second-stage command. It is not part of the default retrieval run because it may download large artifacts and consume much more model context.

```powershell
python scripts\read_papers.py `
  --papers-json outputs\multi-agent-connectivity-control\papers.json `
  --query "multi agent connectivity control" `
  --reading-limit 5 `
  --reading-selection auto
```

Reading mode uses this priority:

1. arXiv LaTeX source, following the popular `read-arxiv-paper` pattern: normalize to `https://arxiv.org/src/<arxiv_id>`, cache the source archive, unpack it, find the TeX entrypoint, and recursively read included TeX files.
2. Open-access PDF fallback from arXiv PDF or `open_access_url`, saved under `pdfs/` and text-extracted with `pdftotext` when available.
3. Metadata-only reading note when no LaTeX source or usable open PDF is available.

It writes `arxiv_sources/`, `pdfs/`, `paper_texts/`, `reading_reports/`, `pdf_manifest.csv`, and `reading_index.md`.

## 显式论文阅读模式

论文阅读是第二阶段命令，不会默认触发，因为它可能下载较大的论文源码/PDF，并消耗更多上下文。

```powershell
python scripts\read_papers.py `
  --papers-json outputs\multi-agent-connectivity-control\papers.json `
  --query "multi agent connectivity control" `
  --reading-limit 5 `
  --reading-selection auto
```

阅读优先级：

1. 优先使用 arXiv LaTeX source：规范化为 `https://arxiv.org/src/<arxiv_id>`，缓存源码包，解包，寻找 TeX 入口文件，并递归读取 `\input` / `\include`。
2. 如果没有 LaTeX source，则使用开放获取 PDF fallback，保存到 `pdfs/`，并在本机有 `pdftotext` 时抽取文本。
3. 如果 LaTeX 和开放 PDF 都不可用，则生成 metadata-only 阅读笔记。

输出包括 `arxiv_sources/`、`pdfs/`、`paper_texts/`、`reading_reports/`、`pdf_manifest.csv` 和 `reading_index.md`。

## Paper Trace Mode

Paper trace mode starts from one seed paper and searches outward through references, citations, citation contexts, and author trajectories.

```powershell
python scripts\trace_paper.py `
  --paper "10.1109/tnse.2021.3139045" `
  --limit 30 `
  --openalex `
  --output-dir outputs\trace-connectivity-control
```

It produces:

- `paper_trace.json`: structured trace data.
- `paper_trace.csv`: table of related papers.
- `paper_trace_report.md`: Chinese paper-centric trace report.

Trace mode distinguishes:

- likely predecessors: papers referenced by the seed paper;
- follow-up development: papers citing the seed paper;
- deep/method citations: citing papers with citation contexts, intents, or influential flags suggesting method use, comparison, extension, or close dependence;
- author latest work: recent papers by seed authors and related-method authors.

## 以文找文模式

以文找文模式从一篇种子论文出发，沿参考文献、后续引用、引用上下文和作者轨迹向外追踪。

```powershell
python scripts\trace_paper.py `
  --paper "10.1109/tnse.2021.3139045" `
  --limit 30 `
  --openalex `
  --output-dir outputs\trace-connectivity-control
```

输出包括：

- `paper_trace.json`：结构化追踪结果。
- `paper_trace.csv`：相关论文表格。
- `paper_trace_report.md`：中文以文找文报告。

该模式区分：

- 可能的前身：种子论文引用的参考文献；
- 后续发展：引用种子论文的后续论文；
- 深度/方法引用：引用上下文、citation intent 或 influential 标记显示其使用、比较、扩展或依赖本文方法的论文；
- 作者最新动态：种子论文作者和相关方法作者的近期研究。

## Outputs

Each run can produce:

- `papers.csv`: normalized spreadsheet-friendly records.
- `papers.json`: normalized records with scores and source metadata.
- `papers.bib`: BibTeX export.
- `report.md`: topic brief by default, or ranked list with `--report-style list`.
- `topic_brief.md`: deterministic Chinese topic briefing.
- `search_log.md`: reproducibility log.
- `errors.log`: connector errors, only when failures occur.
- `web_supplement.md`: Codex-authored web supplement notes.
- `deep_research_report.md`: Codex-authored final synthesis.
- `reading_reports/` and `reading_index.md`: explicit paper-reading outputs.
- `paper_trace_report.md`, `paper_trace.json`, and `paper_trace.csv`: explicit paper-trace outputs.

## 输出文件

每次运行可生成：

- `papers.csv`：适合表格筛选的归一化记录。
- `papers.json`：带评分和来源信息的归一化记录。
- `papers.bib`：BibTeX 导出。
- `report.md`：默认主题简报；使用 `--report-style list` 可生成旧版排序列表。
- `topic_brief.md`：确定性中文主题简报。
- `search_log.md`：可复现检索日志。
- `errors.log`：仅在连接器失败时生成。
- `web_supplement.md`：Codex 撰写的网页补充记录。
- `deep_research_report.md`：Codex 撰写的最终综合调研报告。
- `reading_reports/` 和 `reading_index.md`：显式论文阅读模式输出。
- `paper_trace_report.md`、`paper_trace.json` 和 `paper_trace.csv`：显式以文找文模式输出。

## Hybrid Deep Research Workflow

1. Run the CLI to build a reproducible academic corpus.
2. Inspect `search_log.md`, `papers.json`, and `topic_brief.md`.
3. Use Codex web search only as a supplement for author pages, project pages, open PDFs, recent preprints, and reliable context.
4. Record supplemental evidence in `web_supplement.md`.
5. Write `deep_research_report.md` from the API corpus plus the web supplement.

## 混合式 Deep Research 流程

1. 先运行 CLI，建立可复现的学术语料。
2. 检查 `search_log.md`、`papers.json` 和 `topic_brief.md`。
3. 仅将 Codex 网页搜索作为补充，用于作者主页、项目页、开放 PDF、近期预印本和可靠背景信息。
4. 将网页补充证据记录到 `web_supplement.md`。
5. 基于 API 语料和网页补充撰写 `deep_research_report.md`。

## Repository Layout

```text
scholarly-deep-research/
  SKILL.md
  agents/
    openai.yaml
  references/
    api-notes.md
    deep-research-workflow.md
    report-template-zh.md
  scripts/
    lit_retrieve.py
    read_papers.py
    trace_paper.py
```

## Validation

```powershell
python -m py_compile scripts\lit_retrieve.py
python C:\Users\TanWei\.codex\skills\.system\skill-creator\scripts\quick_validate.py .
```

## License

No license has been selected yet. Add a license before publishing for broad reuse.

## 许可证

当前尚未选择许可证。如需公开复用，请在发布前添加合适的 license。
