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
- Avoids Google Scholar scraping, ResearchGate scraping, publisher scraping, and paywall bypassing.

## 功能

- 支持 OpenAlex、Semantic Scholar、Crossref、PubMed、arXiv，以及需要 API key 的 IEEE Xplore。
- 将论文元数据归一化为 CSV、JSON、BibTeX。
- 按 DOI、arXiv ID、标题相似度、标题-作者-年份信号去重。
- 使用透明评分公式对论文排序。
- 默认生成中文 `topic_brief.md`。
- 提供混合式工作流，让 Codex 基于网页补充生成 `web_supplement.md` 和 `deep_research_report.md`。
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
