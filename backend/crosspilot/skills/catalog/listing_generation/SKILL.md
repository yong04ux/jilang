---
name: listing_generation
title: Listing 生成
description: 按已确认的商品事实生成标题、五点、描述与 Search Terms，并做事实对齐质检；用户要写文案时使用。
summary: 按商品事实生成标题、五点、描述与 Search Terms，并做事实对齐质检。
category: 竞品与Listing
keywords: [listing, 文案, 标题, 五点, 描述, search terms]
version: 1.0.0
renderer: listing
uses_llm: true
credits: 2
status: available
executor_type: function
input_model: crosspilot.skills.inputs:ListingGenerationInput
executor: crosspilot.skills.executors:listing_generation
output_schema: output.schema.json
---

# Listing 生成

## 何时使用

用户已经有确认过的商品事实（规格、材质、卖点、目标站点），需要一份可直接编辑的
Listing 草稿时使用。可选关联一份竞品报告，用来参考差异化卖点。

## 输入要求

- 商品事实必填：名称、规格、关键卖点等；
- 站点与目标语言决定平台规则和措辞；
- 禁用词、语气、篇幅要求按用户约束传入，不要自行放宽。

## 执行边界

- 有可用模型时由模型生成；没有配置密钥时退回规则引擎，产出会标明实际引擎，不编造事实；
- 缺少可引用的商品事实时停止并提示补资料，**不允许编造参数**；
- 产出附带事实台账，后续质检按台账核对数字与卖点出处。
