---
name: data_validation
title: 数据校验
description: 解析 CSV / JSON / Excel，逐行校验竞品字段并定位到具体行与列；用户想先检查数据文件再分析时使用。
summary: 解析 CSV / JSON / Excel，逐行校验字段并定位到具体行与列。
category: 数据分析
keywords: [校验, csv, json, excel, 数据文件, 字段, 导入, 格式]
version: 1.0.0
renderer: table
requires: []
credits: 1
status: available
executor_type: function
input_model: crosspilot.skills.inputs:DataValidationInput
executor: crosspilot.skills.executors:data_validation
output_schema: output.schema.json
---

# 数据校验

## 何时使用

用户手里有一份竞品数据文件，想在分析之前确认字段是否完整、哪几行有问题时使用。
校验通过的数据会存成可复用批次，竞品分析可以直接按批次取数。

## 输入要求

- 文件名 + 文件内容（base64）；支持 CSV / JSON / Excel；
- 文件超过配置上限时明确报错，要求拆分。

## 执行边界

- 文件根本读不出来才算参数错误；行级错误是正常结果，逐行报告；
- 不替用户猜测字段含义，字段映射问题会指到具体列。
