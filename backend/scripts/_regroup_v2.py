"""monorepo 重组 import 改写 v2（修复版）。

背景：``_regroup_imports.py``（v1）有 bug——用 match+重建行的方式改写，
把 ``from X import 名字1, 名字2`` 的**名字部分丢掉了**，277 处全部受损。
本脚本从 pre-flatten 快照（原始包结构，import 名字完好）恢复文件内容，
再用**保留尾部**的正则重新改写，写入 monorepo 新位置。

v1 的教训：行级重写必须捕获并原样带回 import 的名字（含多行括号形式与行尾注释）。

映射同 v1：
  engine/       analysis listing listing_llm facts lexicon textutils rules scrubbing
  llm/          llm providers provider_configs model_settings
  market/       marketplaces marketplace_provider
  persistence/  db migrations storage secrets
  ingest/       importers
  demo/         seed demo_data demo_mode
  包根保留      app cli config version models tenancy auth worker worker_service
  子包原名      api agent services
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

SNAPSHOT = Path(r"D:\my-project\CrossPilot\_backup\pre-flatten-20261021-003118")
NEW_ROOT = Path(r"D:\my-project\CrossPilot\backend")

GROUPS = {
    "analysis": "engine.analysis",
    "listing": "engine.listing",
    "listing_llm": "engine.listing_llm",
    "facts": "engine.facts",
    "lexicon": "engine.lexicon",
    "textutils": "engine.textutils",
    "rules": "engine.rules",
    "scrubbing": "engine.scrubbing",
    "llm": "llm.llm",
    "providers": "llm.providers",
    "provider_configs": "llm.provider_configs",
    "model_settings": "llm.model_settings",
    "marketplaces": "market.marketplaces",
    "marketplace_provider": "market.marketplace_provider",
    "db": "persistence.db",
    "migrations": "persistence.migrations",
    "storage": "persistence.storage",
    "secrets": "persistence.secrets",
    "importers": "ingest.importers",
    "seed": "demo.seed",
    "demo_data": "demo.demo_data",
    "demo_mode": "demo.demo_mode",
    "app": "app",
    "config": "config",
    "version": "version",
    "models": "models",
    "tenancy": "tenancy",
    "auth": "auth",
    "worker": "worker",
    "worker_service": "worker_service",
    "api": "api",
    "agent": "agent",
    "services": "services",
}

ROOT_MODULES = {"app", "config", "models", "tenancy", "auth", "worker", "worker_service"}

# 包根文件的 `from .X import ...`（X 为扁平模块名）；__future__/标准库不带点，天然不匹配
RE_ROOT = re.compile(r"^(\s*)from \.(\w[\w.]*) import (.*)$")
# 子包文件的 `from ..X import ...`
RE_SUB = re.compile(r"^(\s*)from \.\.(\w[\w.]*) import (.*)$")
# tests/scripts 的 `from crosspilot.X import ...`
RE_ABS = re.compile(r"^(\s*)from crosspilot\.(\w[\w.]*) import (.*)$")
# 包级 __version__ 的三种写法
RE_VER_ROOT = re.compile(r"^(\s*)from \. import __version__\s*$")
RE_VER_SUB = re.compile(r"^(\s*)from \.\. import __version__\s*$")
RE_VER_ABS = re.compile(r"^(\s*)from crosspilot import __version__\s*$")

changes: list[tuple[Path, str]] = []


def mapped_path(stem: str) -> str:
    """扁平模块名 -> 包内新路径（点号）。"""
    return GROUPS.get(stem, stem)


def rewrite_package_line(line: str, dest_subpkg: str | None) -> str:
    """dest_subpkg：None=包根文件；否则为 api/agent/services 之一。"""
    m = RE_VER_ROOT.match(line)
    if m and dest_subpkg is None:
        return f"{m.group(1)}from .version import __version__"
    m = RE_VER_SUB.match(line)
    if m and dest_subpkg is not None:
        return f"{m.group(1)}from ..version import __version__"

    if dest_subpkg is None:
        m = RE_ROOT.match(line)
        if not m:
            return line
        indent, dotted, names = m.groups()
        seg0 = dotted.split(".", 1)[0]
        if seg0 not in GROUPS:
            return line
        mapped = mapped_path(seg0)
        rest = dotted[len(seg0):]
        return f"{indent}from .{mapped}{rest} import {names}"

    m = RE_SUB.match(line)
    if not m:
        return line
    indent, dotted, names = m.groups()
    seg0 = dotted.split(".", 1)[0]
    if seg0 not in GROUPS:
        return line
    mapped = mapped_path(seg0)
    rest = dotted[len(seg0):]
    if mapped == dest_subpkg:
        return f"{indent}from .{mapped}{rest} import {names}"
    if mapped.startswith(dest_subpkg + "."):
        return f"{indent}from .{mapped[len(dest_subpkg) + 1:]}{rest} import {names}"
    return f"{indent}from ..{mapped}{rest} import {names}"


def rewrite_absolute_line(line: str) -> str:
    """tests/scripts：from crosspilot.X import ... -> from crosspilot.<新路径> import ..."""
    m = RE_VER_ABS.match(line)
    if m:
        return f"{m.group(1)}from crosspilot.version import __version__"
    m = RE_ABS.match(line)
    if not m:
        return line
    indent, dotted, names = m.groups()
    seg0 = dotted.split(".", 1)[0]
    if seg0 not in GROUPS:
        return line
    mapped = mapped_path(seg0)
    rest = dotted[len(seg0):]
    return f"{indent}from crosspilot.{mapped}{rest} import {names}"


def dest_for(rel: Path) -> Path:
    """快照内的相对路径 -> backend/ 下的新相对路径。"""
    parts = rel.parts
    if parts[0] == "tests" or parts[0] == "scripts":
        return NEW_ROOT / rel
    # crosspilot/ 包内
    assert parts[0] == "crosspilot", rel
    if len(parts) == 1:
        return NEW_ROOT / rel
    if parts[1] in ("api", "agent", "services"):
        return NEW_ROOT / "crosspilot" / parts[1] / parts[2]
    stem = Path(parts[1]).stem
    if stem == "__main__":
        return NEW_ROOT / "crosspilot" / "cli.py"
    if stem == "__init__":
        return NEW_ROOT / "crosspilot" / "__init__.py"
    return NEW_ROOT / "crosspilot" / (mapped_path(stem).replace(".", "/") + ".py")


def main() -> int:
    pkg = SNAPSHOT / "crosspilot"
    targets: list[Path] = []
    targets += sorted(pkg.glob("*.py"))
    for d in ("api", "agent", "services"):
        targets += sorted((pkg / d).glob("*.py"))
    targets += sorted((SNAPSHOT / "tests").glob("*.py"))
    targets += sorted((SNAPSHOT / "scripts").glob("*.py"))

    for src in targets:
        rel = src.relative_to(SNAPSHOT)
        dest = dest_for(rel)
        # __init__.py 保留新版（含目录职责文档），不覆盖
        if dest.name == "__init__.py" and dest.parent == NEW_ROOT / "crosspilot":
            continue
        text = src.read_text(encoding="utf-8")
        is_pkg = rel.parts[0] == "crosspilot"
        dest_subpkg = None
        if is_pkg and len(rel.parts) == 3 and rel.parts[1] in ("api", "agent", "services"):
            dest_subpkg = rel.parts[1]
        out_lines = []
        for line in text.splitlines(keepends=True):
            nl = "\n" if line.endswith("\n") else ""
            body = line.rstrip("\n")
            new = rewrite_package_line(body, dest_subpkg) if is_pkg else rewrite_absolute_line(body)
            if new != body:
                changes.append((dest, body))
            out_lines.append(new + nl)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("".join(out_lines), encoding="utf-8")

    # ---- 测试字符串引用（快照里是原始包路径）----
    string_fixes = {
        NEW_ROOT / "tests" / "test_listing.py": [
            ('__import__("crosspilot.listing"', '__import__("crosspilot.engine.listing"'),
            ('__import__("crosspilot.demo_data"', '__import__("crosspilot.demo.demo_data"'),
        ],
    }
    for path, pairs in string_fixes.items():
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for old, new in pairs:
            if old in text:
                text = text.replace(old, new)
                changes.append((path, old))
        path.write_text(text, encoding="utf-8")

    print(f"恢复并改写 {len({c[0] for c in changes})} 个文件，{len(changes)} 处 import：")
    for dest, old in changes[:40]:
        print(f"  {dest.relative_to(NEW_ROOT.parent)}: {old.strip()[:70]}")
    if len(changes) > 40:
        print(f"  ……另 {len(changes) - 40} 处")
    return 0


if __name__ == "__main__":
    sys.exit(main())
