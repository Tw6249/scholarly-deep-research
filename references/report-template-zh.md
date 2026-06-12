# 中文 Deep Research 报告模板

Use this structure for `deep_research_report.md`.

```markdown
# 主题调研报告：<主题>

## 摘要
用 1-3 段说明主题是什么、为什么重要、当前文献主线是什么、最值得读的论文是哪几类。

## 1. 问题背景与定义
解释核心问题、基本术语、典型系统设定、主要约束和评价指标。

## 2. 检索策略与覆盖范围
说明 API 检索来源、年份、去重后数量、网页补充来源类型，以及“不保证穷尽”的边界。

## 3. 技术路线分类
按方法族组织，而不是按论文逐篇堆叠。每个方法族说明问题设定、代表论文、优势和限制。

## 4. 代表性论文与阅读地图
给出表格：论文、年份、作者、场景、方法角色、为什么要读。

## 5. 研究脉络
按时间说明方法如何演进：早期基础、分布式实现、事件触发/约束控制、近期鲁棒性或应用化趋势。

## 6. 方法对比
比较模型假设、连通度度量、控制结构、通信需求、安全约束、实验验证和可扩展性。

## 7. 局限与开放问题
列出理论、算法、实验、数据、工程化和应用场景上的缺口。

## 8. 建议阅读顺序
按“综述/基础 -> 核心方法 -> 近期进展 -> 应用/实验”推荐阅读。

## 9. 可复核来源
列出 papers.json、search_log.md、web_supplement.md，以及重要 DOI/arXiv/URL。
```

Avoid turning the final report into a search transcript. Search details belong in `search_log.md`; the report should explain the research topic.
