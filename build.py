"""配布物（スタンドアロン exe）のビルド"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST_DIR = ROOT / "dist" / "ASA_Login"
RELEASE_DIR = ROOT / "release"
RELEASE_ZIP = RELEASE_DIR / "ASA_Login-win64.zip"


def run(cmd: list[str]) -> None:
    print("$", " ".join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)


def main() -> None:
    run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
    run([sys.executable, "-m", "pip", "install", "pyinstaller>=6.0"])

    if (ROOT / "build").exists():
        shutil.rmtree(ROOT / "build")
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)

    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "ASA_Login.spec"])

    if not DIST_DIR.exists():
        raise SystemExit(f"ビルド出力が見つかりません: {DIST_DIR}")

    for folder in ("templates", "templates/buttons", "logs"):
        (DIST_DIR / folder).mkdir(parents=True, exist_ok=True)

    shutil.copy2(ROOT / "config.example.yaml", DIST_DIR / "config.example.yaml")
    shutil.copy2(ROOT / "README.md", DIST_DIR / "README.md")
    readme_dist = DIST_DIR / "使い方.txt"
    readme_dist.write_text(
        """ASA_Login 配布版

【起動】
  ASA_Login.exe をダブルクリック

【初回】
  1. 「セットアップ」でサーバー一覧画面を登録
  2. ゲームで接続先サーバーを選択（オレンジ色）
  3. 「開始」を押す

【設定】
  config.yaml … 自動生成（初回起動時）
  templates/ … セットアップで保存した画面画像
  logs/ … ログ出力先

【注意】
  Python のインストールは不要です。
  Windows 10/11 64bit 向けです。
  自己責任でご利用ください。
""",
        encoding="utf-8",
    )

    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    if RELEASE_ZIP.exists():
        RELEASE_ZIP.unlink()
    shutil.make_archive(str(RELEASE_ZIP.with_suffix("")), "zip", ROOT / "dist", "ASA_Login")

    print()
    print("ビルド完了")
    print(f"  フォルダ: {DIST_DIR}")
    print(f"  ZIP:      {RELEASE_ZIP}")


if __name__ == "__main__":
    main()
