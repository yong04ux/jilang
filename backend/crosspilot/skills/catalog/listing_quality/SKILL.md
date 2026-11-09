---
name: listing_quality
title: Listing 质检
description: 对已有 Listing 草稿核对数字与卖点的出处，指出必须改和待确认的地方；用户想检查文案是否可信时使用。
summary: 对已有草稿核对数字与卖点的出处，指出必须改和待确认的地方。
category: 竞品与Listing
keywords: [质检, 核对, 事实, 出处, 检查文案, 草稿, 数字]
version: 1.0.0
renderer: table
requires: []
credits: 1
status: available
executor_type: function
input_model: crosspilot.skills.inputs:ListingQualityInput
executor: crosspilot.skills.executors:listing_quality
output_schema: output.schema.json
---

# Listing 质检

## 何时使用

用户已经有一份 Listing 草稿（刚生成的或手工改过的），想知道哪些数字、认证、
卖点没有出处，哪些需要再确认时使用。

## 输入要求

- 一份已有的 Listing 草稿（按 id 选择，或由调用方直接传入草稿对象）。

## 执行边界

- 读草稿里已有的事实台账与质检结果，不重新实现一套规则；
- 只报告问题，不擅自改写草稿。
