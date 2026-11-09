---
name: review_mining
title: 评论痛点挖掘
description: 从已有竞品分析报告里归纳评论主题、频次与占比；用户已经有一份报告、只想看评论痛点时使用。
summary: 从已有分析报告里归纳评论主题、频次与占比，只读不重算。
category: 产品运营
keywords: [评论, 痛点, 差评, 需求, 顾虑]
version: 1.0.0
renderer: table
requires: []
credits: 1
status: available
executor_type: function
input_model: crosspilot.skills.inputs:ReviewMiningInput
executor: crosspilot.skills.executors:review_mining
output_schema: output.schema.json
---

# 评论痛点挖掘

## 何时使用

用户已经跑过竞品分析，报告里带有评论样本，想单独看痛点、需求与购买顾虑时使用。

## 输入要求

- 一份已有的分析报告（按 id 选择，或由调用方直接传入报告对象）。

## 执行边界

- 只读报告里已有的评论样本，不重新抓取、不重新计算统计；
- 每条结论必须带原文或出处，没有样本就如实报告样本为空。
