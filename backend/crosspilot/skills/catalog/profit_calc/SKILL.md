---
name: profit_calc
title: 成本与利润测算
description: 拆解成本、计算盈亏平衡与回本销量，给出三档定价和敏感性分析；用户在定价或核算利润时使用。
summary: 拆成本、算盈亏平衡与回本销量，给出三档定价和敏感性。
category: 财务核算
keywords: [利润, 成本, 定价, 盈亏, 回本, 毛利]
version: 1.0.0
renderer: chart
requires: []
credits: 1
status: available
executor_type: function
input_model: crosspilot.engine.profit:ProfitRequest
executor: crosspilot.skills.executors:profit_calc
output_schema: output.schema.json
---

# 成本与利润测算

## 何时使用

用户想给一个商品定价、判断某档价格会不会亏、或者想知道卖多少件回本时使用。

## 输入要求

- 采购/头程/平台佣金/FBA 等成本项；缺的项按用户给的填，缺失项要显式说明；
- 售价区间、目标利润率如有就传入。

## 执行边界

- 纯计算，不调用模型，也不落库；
- 所有金额单位与币种必须和输入一致，不擅自换算。
