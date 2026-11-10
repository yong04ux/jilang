---
name: competitor_analysis
title: 竞品分析
description: 按竞品价格、评分与评论计算价格定位、评论主题和差异化机会；用户提供竞品明细或已导入的数据批次时使用。
summary: 按竞品价格、评分与评论算价格定位和差异化机会，每条结论都挂出处。
category: 竞品与Listing
keywords: [竞品, 竞品分析, 价格, 定价, 评论, 差异化]
version: 1.0.0
renderer: report
requires: []
credits: 1
status: available
executor_type: function
input_model: surge.skills.inputs:CompetitorAnalysisInput
executor: surge.skills.executors:competitor_analysis
output_schema: output.schema.json
---

# 竞品分析

## 何时使用

用户手里有一批竞品（表单填写或已导入的数据批次），想看清价格带、卖点覆盖、
评论痛点，并据此判断自己可以从哪里差异化时使用。

## 输入要求

- 竞品明细至少 1 条，或一个已导入的数据批次 id；
- 商品名称必填；规格、卖点、价格有就填，没有不要编造；
- 数据来自示例时必须显式选择 `demo`，产出会一路标记 `is_demo`。

## 执行边界

- 只做确定性统计与归纳，不调用大模型；
- 样本不足时仍给结论，但会标注为部分结果并说明原因；
- 产出落库为分析报告，后续的评论挖掘、市场总结、Listing 生成都引用这份报告。
