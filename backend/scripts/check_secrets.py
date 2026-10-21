"""密钥/凭据自检：扫描仓库里"看起来是真凭据"的字样，推送前跑一遍。

为什么需要它：`.gitignore` 只挡已知的 `.env`，挡不住有人把 Key 贴进代码、文档、
测试或 `render.yaml`。之前推送时靠人工过目，容易漏。

设计原则：

1. **只报高置信度特征**，不做泛化的"含有 password 字样就报警"，否则误报会让人关掉它。
2. **绝不回显明文**：输出里只给掩码后的片段，避免脚本自己把密钥泄到 CI 日志。
3. **白名单按"行内标记"**：示例值（example / sample / dummy / fake / placeholder / <...>）
   或真实部署里本就公开的本地默认口令（`postgres:postgres@`）不报。
4. `.example` 文件整体放行：它存在的意义就是放占位值。
5. **测试文件的构造密钥用显式文件级标记放行**，而不是猜"像不像真的"：
   在文件前 5 行写 ``check_secrets: allow-placeholders`` 即可。
   这样意图明确；真有密钥误入测试文件、又没人加标记时仍然会报。

用法：

```bash
cd backend
python scripts/check_secrets.py            # 有问题时 exit 1
python scripts/check_secrets.py --verbose  # 顺带打印扫描范围
python scripts/check_secrets.py --path=/tmp/x  # 自测用：只扫指定目录
```
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_ROOT.parent

SKIP_PARTS = {
    "node_modules",
    "lib",
    ".git",
    "__pycache__",
    ".pytest_cache",
    "data",
    ".venv",
    "venv",
    "build",
    "dist",
    "crosspilot.egg-info",
    "_backup",
}

SCAN_DIRS = ("crosspilot", "tests", "scripts", "config")
REPO_ROOT_FILES = (
    "README.md",
    "render.yaml",
    "vercel.json",
    "docker-compose.yml",
    "backend/README.md",
    "backend/requirements.txt",
    "backend/pyproject.toml",
    "backend/pytest.ini",
    "backend/.env.example",
    "backend/config/render.env.example",
)

TEXT_SUFFIXES = {
    ".py", ".md", ".json", ".html", ".css", ".js", ".mjs",
    ".yml", ".yaml", ".txt", ".ini", ".cfg", ".toml", ".sh",
    ".ps1", ".properties", ".sql", ".env", ".example",
}

# (名称, 正则)：只放"几乎不可能是误报"的模式
PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("OpenAI/DeepSeek 风格密钥", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    ("AWS Access Key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub Token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}")),
    ("GitLab Token", re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}")),
    ("Slack Token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    ("PEM 私钥块", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----")),
    ("裸 base64 私钥体", re.compile(r"\bMII[A-Za-z0-9+/]{40,}")),
    ("带口令的连接串", re.compile(r"\bpostgres(?:ql)?://[^:\s/@]+:[^@\s]{6,}@")),
)

#: 行内出现这些标记就认为是示例，不报
ALLOW_MARKERS = (
    "example", "sample", "dummy", "fake", "placeholder", "changeme",
    "redacted", "your-", "your_", "xxx", "***", "...", "<", "{{", "}}",
    # 本地开发默认口令：本来就是公开的，不是秘密
    "postgres:postgres@", "crosspilot:crosspilot@", "password@localhost",
)


#: 文件级豁免：前 10 行出现该标记，整个文件跳过（用于测试里的构造密钥）
ALLOW_FILE_MARKER = "check_secrets: allow-placeholders"
#: 只看文件头，避免有人把标记塞进业务代码中段
MARKER_WINDOW = 10


def _mask(token: str) -> str:
    """只保留头尾，中间打码；长度不足时全打码。"""
    if len(token) <= 8:
        return "*" * len(token)
    return f"{token[:4]}{'*' * max(4, len(token) - 8)}{token[-4:]}"


def _iter_files(roots: list[Path] | None = None) -> list[Path]:
    files: list[Path] = []
    if roots:
        for root in roots:
            if root.is_dir():
                files.extend(root.rglob("*"))
            elif root.is_file():
                files.append(root)
    else:
        for name in SCAN_DIRS:
            base = BACKEND_ROOT / name
            if base.exists():
                files.extend(base.rglob("*"))
        for name in REPO_ROOT_FILES:
            candidate = REPO_ROOT / name
            if candidate.is_file():
                files.append(candidate)
    result = []
    for path in files:
        if not path.is_file():
            continue
        if any(part in SKIP_PARTS for part in path.parts):
            continue
        if path.suffix not in TEXT_SUFFIXES:
            continue
        result.append(path)
    return sorted(set(result))


def main(argv: list[str]) -> int:
    roots = [
        Path(arg.split("=", 1)[1])
        for arg in argv
        if arg.startswith("--path=") and arg.split("=", 1)[1]
    ]
    files = _iter_files(roots or None)
    if "--verbose" in argv:
        for path in files:
            print("scan:", path.relative_to(REPO_ROOT).as_posix())

    problems: list[str] = []
    for path in files:
        # .example 文件整体放行：它存在的意义就是放占位值
        if path.name.endswith(".example"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if ALLOW_FILE_MARKER in "\n".join(text.splitlines()[:MARKER_WINDOW]):
            continue
        try:
            label_base = BACKEND_ROOT if path.is_relative_to(BACKEND_ROOT) else REPO_ROOT
            label = path.relative_to(label_base).as_posix()
        except ValueError:  # --path 指向仓库外（自测）
            label = str(path)
        for line_no, line in enumerate(text.splitlines(), 1):
            lowered = line.lower()
            if any(marker in lowered for marker in ALLOW_MARKERS):
                continue
            for kind, pattern in PATTERNS:
                match = pattern.search(line)
                if match is None:
                    continue
                problems.append(f"{label}:{line_no}: {kind} → {_mask(match.group(0))}")

    print(f"checked {len(files)} files")

    if problems:
        print("POSSIBLE SECRETS:")
        for item in problems:
            print(" -", item)
        print(
            "\n处理建议：把真实值移出仓库（.env / 平台环境变量），"
            "在代码里只留占位；若确属示例，请在该行加上 example / dummy 等标记。"
        )
        return 1
    print("NO SECRETS FOUND")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
