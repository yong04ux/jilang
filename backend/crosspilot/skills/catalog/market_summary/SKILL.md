---
name: market_summary
title: 市场机会总结
description: 把竞品分析报告里已经算出的结论归纳成机会判断；用户要一段可读的市场结论时使用。
summary: 把报告里已经算出来的结论归纳成机会判断，不调用模型、不加新数字。
category: 竞品与Listing
keywords: [市场, 机会, 总结, 结论]
version: 1.0.0
renderer: report
requires: []
credits: 1
status: available
executor_type: function
input_model: crosspilot.skills.inputs:MarketSummaryInput
executor: crosspilot.skills.executors:market_summary
output_schema: output.schema.json
---

# 市场机会总结

## 何时使用

用户已经有一份竞品分析报告，只想要一段结论性的市场判断（而不是逐项数据）时使用。

## 输入要求

- 一份已有的分析报告（按 id 选择，或由调用方直接传入报告对象）。

## 执行边界

- 只引用报告里已有的结论，不调用模型、不新增数字；
- 数据是示例时必须带 `data_is_demo` 标记，并列出结论的局限。
