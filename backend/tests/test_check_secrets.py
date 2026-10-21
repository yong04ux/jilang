"""密钥扫描脚本的自测：能抓真密钥、不误报示例、回显时打码。"""

# check_secrets: allow-placeholders — 本文件的 API Key 都是构造的假值

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = BACKEND_ROOT / "scripts" / "check_secrets.py"
FAKE_KEY = "sk-" + "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6"


def run_scan(target: Path | None = None) -> subprocess.CompletedProcess[str]:
    args = [sys.executable, str(SCRIPT)]
    if target is not None:
        args.append(f"--path={target}")
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8")


def test_detects_real_looking_key_and_masks_it(tmp_path):
    (tmp_path / "leak.py").write_text(f'KEY = "{FAKE_KEY}"\n', encoding="utf-8")

    result = run_scan(tmp_path)

    assert result.returncode == 1, result.stdout
    assert "POSSIBLE SECRETS" in result.stdout
    assert FAKE_KEY not in result.stdout, "脚本把明文密钥打印出来了"
    assert "sk-" in result.stdout, "至少要让用户知道是哪一类凭据"


def test_example_file_is_allowed(tmp_path):
    # .example 文件存在的意义就是放占位值
    (tmp_path / "settings.example").write_text(
        f'KEY = "{FAKE_KEY}"\n', encoding="utf-8"
    )
    assert run_scan(tmp_path).returncode == 0


def test_inline_example_marker_is_allowed(tmp_path):
    (tmp_path / "doc.md").write_text(
        f'KEY = "{FAKE_KEY}"  # example only\n', encoding="utf-8"
    )
    assert run_scan(tmp_path).returncode == 0


def test_file_level_marker_is_allowed(tmp_path):
    (tmp_path / "fake_test.py").write_text(
        f"# check_secrets: allow-placeholders\nKEY = \"{FAKE_KEY}\"\n",
        encoding="utf-8",
    )
    assert run_scan(tmp_path).returncode == 0


def test_private_key_block_is_detected(tmp_path):
    (tmp_path / "id.py").write_text(
        '"""-----BEGIN RSA PRIVATE KEY-----"""\n', encoding="utf-8"
    )
    assert run_scan(tmp_path).returncode == 1


def test_repository_is_clean():
    result = run_scan()
    assert result.returncode == 0, result.stdout
    assert "NO SECRETS FOUND" in result.stdout
