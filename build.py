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


def bundle_manual(dist_dir: Path) -> None:
    """配布物用の HTML 取扱説明書と参照画像を配置する"""
    docs_dir = dist_dir / "docs"
    samples_src = ROOT / "docs" / "setup_samples"
    samples_dst = docs_dir / "setup_samples"
    samples_dst.mkdir(parents=True, exist_ok=True)

    shutil.copy2(ROOT / "docs" / "manual.html", docs_dir / "manual.html")
    for png in samples_src.glob("*.png"):
        shutil.copy2(png, samples_dst / png.name)

    (dist_dir / "取扱説明書.html").write_text(
        """<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="refresh" content="0; url=docs/manual.html">
  <title>ASA_Login 取扱説明書</title>
</head>
<body>
  <p><a href="docs/manual.html">ASA_Login 取扱説明書</a>を開いています…</p>
</body>
</html>
""",
        encoding="utf-8",
    )


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

    sys.path.insert(0, str(ROOT))
    from src.default_assets import seed_button_templates

    seed_button_templates(DIST_DIR / "templates" / "buttons")

    bundled_buttons = ROOT / "assets" / "defaults" / "buttons"
    dist_buttons = DIST_DIR / "templates" / "buttons"
    for png in bundled_buttons.glob("*.png"):
        shutil.copy2(png, dist_buttons / png.name)

    shutil.copy2(ROOT / "config.example.yaml", DIST_DIR / "config.example.yaml")
    shutil.copy2(ROOT / "README.md", DIST_DIR / "README.md")
    bundle_manual(DIST_DIR)
    readme_dist = DIST_DIR / "使い方.txt"
    readme_dist.write_text(
        """ASA_Login 配布版

【起動】
  ASA_Login.exe をダブルクリック

【取扱説明書】
  取扱説明書.html または docs/manual.html をブラウザで開いてください

【初回】
  1. 「セットアップ」でサーバー一覧画面を登録
  2. ゲームで接続先サーバーを選択（オレンジ色）
  3. 「開始」を押す

【設定】
  config.yaml … 自動生成（初回起動時）
  templates/ … セットアップで保存した画面画像
  templates/buttons/ … ボタン認識用画像（PNG を差し替え可能）
    join_game.png … ④枚タイル（左寄り JOIN GAME）
    join_game_center.png … ⑤枚タイル（中央 JOIN GAME）
    login_success.png … ③ ログイン成功 HUD（右下）
  logs/asa_login_user.log … わかりやすいログ
  logs/asa_login_detail.log … 詳細ログ（原因調査用）

【ボタン画像の差し替え】
  templates/buttons/ 内の PNG を同じファイル名のまま上書きしてください。
  例: join_server_list.png, join_mods.png, cancel_failed.png など

【Discord 通知（任意）】
  GUI「Discord 通知」タブで Webhook を設定
  成功・失敗・エラー終了時に通知（停止ボタンでは通知しない）
  詳細は 取扱説明書.html の「Discord 通知」を参照

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
