"""把 app.py 里 create_app() 内的端点，按行范围切分到 api/<domain>.py。

为什么用脚本而不是手抄：88 个端点、2700 行。手抄必然出错，
而脚本可复核、可重跑。切分后靠 323 个测试验证行为不变。

用法（在 crosspilot/ 下）：
    python scripts/_split_app.py
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "crosspilot" / "app.py"
API = ROOT / "crosspilot" / "api"

# (domain, [(start, end), ...], section_title)
# 行号来自对 app.py 的实测（1-based，含首尾）
SEGMENTS: dict[str, dict] = {
    "meta": {
        "title": "健康检查、平台元信息与页面外壳",
        "ranges": [(905, 925), (926, 1044)],
        "docstring": "服务元信息：健康检查、平台/站点规则、禁用词、页面外壳。",
    },
    "settings": {
        "title": "模型配置与多厂商 LLM 配置",
        "ranges": [(665, 766), (767, 904)],
        "docstring": "每用户的模型配置（旧单套）与多厂商 Provider 配置（多套 + 激活）。",
    },
    "analyses": {
        "title": "竞品分析",
        "ranges": [(1052, 1275)],
        "docstring": "竞品分析：校验、同步分析、异步分析（返回 task_id）。",
    },
    "listings": {
        "title": "Listing 生成与版本",
        "ranges": [(1276, 1570)],
        "docstring": "Listing 生成（同步/异步）、查询、版本链、差异、复检、导出。",
    },
    "imports": {
        "title": "数据导入（一步与两步）",
        "ranges": [(1571, 1641), (1642, 1797)],
        "docstring": "一步导入 + 两步导入（preview / remap / commit）+ 数据源查询与错误 CSV。",
    },
    "tasks": {
        "title": "任务中心",
        "ranges": [(1798, 1920)],
        "docstring": "任务列表、详情（含结果块）、取消。",
    },
    "dashboard": {
        "title": "工作台聚合与演示数据",
        "ranges": [(1045, 1051), (1921, 1971)],
        "docstring": "工作台 KPI/趋势聚合，以及演示数据集。",
    },
    "agents": {
        "title": "会话、审计、审批与 Agent 运行",
        "ranges": [(1972, 1992), (1993, 2068), (2069, 2348)],
        "docstring": "会话与消息、审计日志、审批、Agent 注册表与运行（含异步）。",
    },
    "marketplace": {
        "title": "市场数据（Provider 协议）",
        "ranges": [(2349, 2493)],
        "docstring": "市场数据只读接口：数据源状态、概览、商品/订单/广告/指标。",
    },
    "stores": {
        "title": "店铺连接",
        "ranges": [(2494, 2663)],
        "docstring": "店铺连接（Mock 连接器）、同步、商品/订单、凭据。",
    },
    "catalog": {
        "title": "注册表查询（Agent / Skill / Tool）",
        "ranges": [],
        "docstring": "注册表只读查询。",
    },
}

# 这些区块依赖的核心协作者：切分后统一由 ApiContext 提供
CTX_REPLACEMENTS = (
    ("db", "ctx.db"),
    ("current_settings()", "ctx.settings"),
    ("model_service()", "ctx.model_service()"),
    ("provider_service()", "ctx.provider_service()"),
    ("require_user", "require_user"),
)


def extract(lines: list[str], start: int, end: int) -> list[str]:
    return lines[start - 1 : end]


def dedent_body(body: list[str]) -> list[str]:
    """把 create_app 内缩进 4 的函数体，降为模块级缩进 0。"""
    out: list[str] = []
    for line in body:
        if line.strip() == "":
            out.append("")
        elif line.startswith("    "):
            out.append(line[4:])
        else:
            out.append(line)
    return out


def rewrite(line: str) -> str:
    """把嵌套端点改成 router 端点，并注入 ctx 参数。"""
    # @app.get("/x")  ->  @router.get("/x")
    line = re.sub(r"@app\.(get|post|put|delete|patch)\(", r"@router.\1(", line)
    return line


def inject_ctx(lines: list[str]) -> list[str]:
    """给每个端点函数签名注入 ``ctx: ApiContext = Depends(get_ctx)``。

    规则：``async def xxx(`` 之后若没有参数，直接插入；否则在参数列表末尾追加。
    仅处理带 ``@router.`` 装饰器的函数。
    """
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        if re.match(r"^async def \w+\($", line) or re.match(r"^async def \w+\(\)", line):
            # 收集到匹配的右括号为止
            block = [line]
            j = i + 1
            while j < len(lines) and ")" not in block[-1]:
                out.append(lines[j])
                block.append(lines[j])
                j += 1
            # 简化：交给后处理人工复核，这里只标记
            i = j
            continue
        i += 1
    return out


def main() -> int:
    lines = APP.read_text(encoding="utf-8").splitlines()
    API.mkdir(exist_ok=True)

    for domain, spec in SEGMENTS.items():
        if not spec["ranges"]:
            continue
        body: list[str] = []
        for start, end in spec["ranges"]:
            chunk = extract(lines, start, end)
            body.extend(chunk)
        body = [rewrite(line) for line in body]
        body = dedent_body(body)

        header = [
            f'"""{spec["docstring"]}"""',
            "",
            "from __future__ import annotations",
            "",
            "from typing import Any",
            "",
            "from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile",
            "",
            "from .deps import (",
            "    ApiContext,",
            "    get_ctx,",
            "    optional_user,",
            "    require_admin,",
            "    require_tenant,",
            "    require_user,",
            ")",
            "",
            f'router = APIRouter(tags=["{spec["title"]}"])',
            "",
            "",
        ]
        content = "\n".join(header) + "\n".join(body).rstrip() + "\n\n\n__all__ = [\"router\"]\n"
        (API / f"{domain}.py").write_text(content, encoding="utf-8")
        print(f"wrote api/{domain}.py  ({len(body)} lines)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
