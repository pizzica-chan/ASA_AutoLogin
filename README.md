# ASA_Login

ARK: Survival Ascended のサーバー参加（ログイン）を自動化する Windows 向けツールです。  
**対象サーバーは事前に選択済み**の前提で、接続に成功するまで自動リトライします。

> 操作フローの詳細は [docs/FLOW.md](docs/FLOW.md) を参照してください。

## 自動化ループ（概要）

```
① サーバー一覧 → JOIN → ② MODS（任意）→ JOIN → ③ ログイン試行
    ├─ 成功 → 完了
    ├─ ③-A → CANCEL → ④ BACK → ⑤ JOIN GAME → ①（リトライ）
    └─ ⑥ → ACCEPT → ⑦ Space → ⑤ JOIN GAME → ①（リトライ）
```

## 配布版（Python 不要）

開発者がビルドした ZIP を展開すると、Python なしで起動できます。

```
ASA_Login/
  ASA_Login.exe      … ダブルクリックで起動
  config.example.yaml
  templates/         … セットアップで自動作成
  logs/
  使い方.txt
```

### ビルド方法（開発者向け）

**ワンクリック:** `build.bat` をダブルクリック

またはコマンドライン:

```bash
pip install -r requirements.txt -r requirements-build.txt
python build.py
```

`dist/ASA_Login/` に exe 一式、`release/ASA_Login-win64.zip` に ZIP が出力されます。

## クイックスタート

```bash
pip install -r requirements.txt
python gui.py            # 起動（初回セットアップも GUI から）
```

1. GUI の「セットアップ」ボタンで登録（コマンドライン不要）
2. 対象サーバーを選択した状態でサーバー一覧を表示（「開始」時に参考画像あり）
3. 「開始」を押す

## セットアップ

GUI の **「セットアップ」** ボタンから **最小モード（推奨）** または **フルモード** を選べます。

### 最小モード（推奨）

**① サーバー一覧だけ**キャプチャすれば動きます。

- エラー時の CANCEL / BACK / MODS JOIN は **同梱ボタン画像** で画面上から自動検出
- **エラー画面をわざと起こしてキャプチャする必要はありません**

### フルモード

解像度や UI が大きく違う場合向け。各画面を個別にキャプチャして精度を上げます。

### 仕組み

| 用途 | 方式 |
|------|------|
| 画面状態の判定 | 画面全体の類似度比較（①は自分のキャプチャ、エラー系は同梱デフォルト可） |
| ボタンクリック | `templates/buttons/` の PNG を画面上から検索（② MODS JOIN 含む） |
| フォールバック | 見つからない場合のみセットアップで登録した座標を使用 |
| 座標のみモード | `matching.click_mode: coordinates_only` — クリックはすべて `ui` の％座標、画像認識は画面遷移判定のみ |

## サブモニター運用

ARK をサブモニターに表示し、GUI の「ARK を表示しているモニター」でそのモニターを選択してください。

環境によってうまく動かない場合は、GUI の「画像認識」タブで一致度やクリック方式を調整してください。

## 注意事項

- 対象サーバーは**手動で選択**しておく必要があります
- SESSION NAME やサーバータブの操作はツール側では行いません
- ボタン画像は exe 横の `templates/buttons/` に配置（初回起動時に `assets/defaults/buttons/` からコピー）。PNG を同じファイル名で差し替え可能
- 同梱の正本はリポジトリ内 `assets/defaults/buttons/`（自動切り出しは廃止、手動で用意した PNG をコミット）
- ⑤ JOIN GAME は `join_game.png`（④枚タイル・左寄り）と `join_game_center.png`（⑤枚タイル・中央）の2種を同梱
- ログは GUI の「ログ」「詳細ログ」タブ、および `logs/asa_login_user.log` / `logs/asa_login_detail.log` に出力
- ゲームの利用規約に違反する可能性があります。自己責任でご使用ください

## ライセンス

MIT License
