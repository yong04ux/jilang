# 离线评测数据集

这个目录放**评测的产物与基线**，代码在 `backend/crosspilot/eval/`。

## 跑法

```bash
cd backend
python -m scripts.eval_agent              # 跑全部，更新 latest.json
python -m scripts.eval_agent --check      # 与基线比，有回归退出码 1（门禁）
python -m scripts.eval_agent --print      # 只打印，不落盘
python -m scripts.eval_agent --dim fact_consistency --limit 5
```

## 用例怎么来的

**生成，不是手写。** 手写几条能守住主干，守不住组合：真实输入是
「商品资料完整度 × 竞品数量 × 是否写文案 × 会不会出错」的笛卡尔积，
漏掉任何一格，那一格的回归就没人看着。

生成器在 `backend/crosspilot/eval/cases.py`，**用固定清单穷举，不用随机数**。
所以同一份代码跑出来的用例 id、输入、期望完全一致——`latest.json` 才能逐条 diff。

四个维度：

| 维度 | 守什么 |
| --- | --- |
| `tool_call` | 选没选对工作流、计划骨架对不对、实跑步骤是否落在计划内且顺序正确 |
| `fact_consistency` | Listing 里的数字能否追回事实、要点有没有引用依据、有没有绝对化用语 |
| `completion` | 给定输入应该以什么结局收尾（完成 / 暂停 / 拦下 / 失败） |
| `recovery` | 注入故障后错误分类对不对、有没有留下不该留的半成品 |

## 文件

| 文件 | 说明 |
| --- | --- |
| `latest.json` | 机器可读结果，**入库**，作为下次比较的基线 |

## 两条边界（写在前面，免得误读）

1. **不评大模型文案质量。** 全程用规则引擎，无网络调用。它衡量的是编排、
   规则引擎与错误处理的行为一致性。
2. **不算调用金额。** 只记 token。仓库没有维护厂商价目表，凭空算出来的钱
   会被当成真数据引用。

## 已知问题

确认过、暂不修的行为登记在 `backend/crosspilot/eval/known_issues.py`。
它们**不算通过也不算未通过**，单独计数，`--check` 不会挡住它们，
但每次报告都会列出来——这样红灯不会因为"看习惯了"而失去意义。
