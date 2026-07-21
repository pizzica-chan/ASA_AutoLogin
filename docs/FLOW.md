# ASA_Login 操作フロー

ARK: Survival Ascended のサーバー参加を自動化する際の画面遷移と、ツールが実行する操作の仕様書です。

## 前提条件

| 項目 | 内容 |
|------|------|
| 対象サーバー | **ユーザーが手動で選択済み**（オレンジでハイライト） |
| 開始画面 | マルチプレイサーバー一覧（MULTIPLAYER SERVERS） |
| ツールが行わないこと | SESSION NAME 検索、サーバータブ切替、サーバー行の選択 |

## 全体フロー

```
┌─────────────────────────────────────────────────────────┐
│  ① サーバー一覧（選択済み）→ 右下 JOIN をクリック          │
└───────────────────────────┬─────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│  ② REQUIRED MODS 画面（任意）→ モーダル左下 JOIN をクリック   │
│     ※ 表示されない場合はスキップ                         │
└───────────────────────────┬─────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│  ③ ログイン試行中（待機）                                │
│     ├─ 成功（ゲーム内画面を検出）→ 完了                   │
│     ├─ ③-A CONNECTION FAILED（サーバー一覧上）          │
│     │      → CANCEL → ④ → ⑤ → ①                        │
│     └─ ⑥ ログインムービー後、タイトル画面で失敗            │
│            → ACCEPT → ⑦ Space → ⑤ JOIN GAME → ①          │
└─────────────────────────────────────────────────────────┘
```

---

## 各ステップの詳細

### ① サーバー一覧画面

| 項目 | 内容 |
|------|------|
| **画面** | MULTIPLAYER SERVERS 一覧 |
| **前提** | 接続先サーバーが既に選択されている（行がオレンジ色） |
| **操作** | 画面**右下**の **JOIN** ボタンをクリック |
| **テンプレート** | `templates/server_list.png` |
| **クリック位置** | `ui.join_server_list` |

**補足:** 検索ボックスへの入力やサーバー行のクリックは行いません。

---

### ② REQUIRED MODS 画面（条件付き）

| 項目 | 内容 |
|------|------|
| **画面** | REQUIRED MODS モーダル |
| **出現条件** | サーバーによっては表示され、されない場合もある |
| **操作** | 表示された場合のみ、モーダル**左下**の **JOIN**（オレンジ色）をクリック |
| **テンプレート** | `templates/required_mods.png`（任意） |
| **クリック位置** | `ui.join_mods` |
| **待機時間** | ① JOIN 後最大 `mods_wait_seconds`（デフォルト 8 秒）で画面出現を監視 |
| **検出方式** | `matching.mods_detect_mode`（`hybrid` / `screen` / `button`、デフォルト `hybrid`）。`hybrid` では画面類似度（中央モーダル領域）と `join_mods` ボタン PNG のいずれかで判定 |

**補足:** 一覧画面右下の JOIN（①）とは別ボタンです。

---

### ③ ログイン試行

| 項目 | 内容 |
|------|------|
| **状態** | 接続処理中（ローディングムービー等） |
| **操作** | 待機のみ（クリックなし） |
| **成功判定** | `templates/in_game.png` と画面の類似度が閾値以上 |
| **タイムアウト** | `result_timeout`（デフォルト 120 秒）。ムービー検出時は `login_movie_timeout`（デフォルト 120 秒）まで延長 |

② の JOIN 後、失敗には **2 パターン** あります。

#### ③-A 失敗（CONNECTION FAILED・サーバー一覧上）

| 項目 | 内容 |
|------|------|
| **画面** | サーバー一覧の上に「CONNECTION FAILED」ダイアログ |
| **本文例** | `This Server is full. Please try again later...` |
| **操作** | **CANCEL** をクリック（ACCEPT は使わない） |
| **テンプレート** | `templates/connection_failed.png` |
| **クリック位置** | `ui.cancel_failed` |
| **復帰** | ④ BACK → ⑤ JOIN GAME → ① |

#### ⑥ 失敗（NETWORK FAILURE・タイトル画面）

| 項目 | 内容 |
|------|------|
| **経路** | ② の JOIN 後、ログイン成功時のような**ムービー**（オレンジ背景の ARK ロゴ等）が流れたあと、**タイトル画面**に戻る |
| **画面** | タイトル画面上の「NETWORK FAILURE MESSAGE」ダイアログ |
| **本文例** | `Server full.` |
| **操作** | **ACCEPT** をクリック |
| **テンプレート** | `templates/network_failure.png` |
| **クリック位置** | `ui.accept_network_failure` |
| **補助テンプレート** | `templates/login_movie.png`（ムービー再生中の待機判定・任意） |
| **復帰** | ACCEPT → **⑦** → Space → **⑤** JOIN GAME → ① |

**補足:** ③-A と ⑥ は排他的です。どちらか一方が発生します。

---

### ⑦ タイトル画面（ACCEPT 後）

| 項目 | 内容 |
|------|------|
| **画面** | ⑥ で ACCEPT を押した後のタイトル画面（エラーダイアログなし） |
| **表示例** | `PRESS [Enter] TO START` / `JOIN LAST SESSION` 等 |
| **操作** | **Space** キーを押す（Enter でも可だが、ツールは Space を送信） |
| **テンプレート** | `templates/title_screen.png`（任意・⑦ 検出用） |
| **遷移先** | ⑤ メインメニュー（④ から BACK したときと同じ画面） |
| **復帰** | ⑤ と同様に **JOIN GAME** → ① |

**補足:** `title_screen.png` が未設定の場合は、⑥ のエラーダイアログが消えるまで待機してから Space を押します。

---

### ④ 空のサーバー一覧

| 項目 | 内容 |
|------|------|
| **画面** | サーバー一覧だが一覧が空（`MULTIPLAYER SERVERS: 0`） |
| **表示** | 中央に `Joining server ...` メッセージ |
| **操作** | 画面**左下**の **BACK** をクリック |
| **テンプレート** | `templates/server_list_empty.png`（任意） |
| **クリック位置** | `ui.back_empty_list` |

**補足:** ③ で CANCEL を押した直後に遷移することが多いです。`server_list_empty.png` 未登録時は `back_empty_list` ボタン PNG で検出可能（座標のみモード含む）。

---

### ⑤ メインメニュー

| 項目 | 内容 |
|------|------|
| **画面** | メインメニュー（DRAGONTOPIA / JOIN GAME 等のカード） |
| **操作** | 中央の **JOIN GAME** カードをクリック |
| **テンプレート** | `templates/main_menu.png`（任意・同梱フォールバックは⑤枚タイル向け） |
| **クリック位置** | `ui.join_game`（1 点。4枚 / 5枚どちらのレイアウトでも、自分の JOIN GAME 位置を登録） |
| **ボタン PNG** | `join_game.png` と `join_game_center.png` を**毎回両方試行**（レイアウト自動判定なし） |
| **遷移先** | ① のサーバー一覧（対象サーバー選択済み） |

**補足:** ④枚タイルでは `join_game_center.png`、⑤枚タイルでは `join_game.png` が当たりやすい。到達判定はボタン PNG 優先、画面テンプレートは補助。

---

## リトライの動き

1. **① → ② → ③** を1回の接続試行とする
2. ③ で失敗した場合:
   - **③-A** … CANCEL → ④ BACK → ⑤ JOIN GAME で ① に戻る
   - **⑥** … ACCEPT → ⑦ Space → ⑤ JOIN GAME で ① に戻る
3. ① から再度ループを実行
4. `retry.max_attempts` が `0` の場合は成功するまで無制限に繰り返す
5. 失敗のたびに `retry.delay_seconds` 秒待機してから次の試行

## 画面判定の仕組み（ハイブリッド）

| 用途 | 方式 |
|------|------|
| **画面状態の判定**（①〜⑦・成功） | 画面全体キャプチャと `templates/*.png` の類似度比較 |
| **ボタンクリック** | `templates/buttons/*.png`（exe 横・差し替え可）を画面上から検索してクリック |
| **フォールバック** | ボタン画像が見つからない場合、`config.yaml` の `ui` 座標でクリック |

- 画面判定の閾値: `matching.screen_threshold`（デフォルト `0.75`）
- ボタン検索の閾値: `matching.button_threshold`（デフォルト `0.75`）、`join_game` は緩い閾値（`button_threshold_relaxed`）も使用
- ボタン画像は **exe 横の `templates/buttons/`** に配置。初回起動時に同梱サンプルをコピーし、同じファイル名で PNG を差し替え可能

### 座標のみモード（`click_mode: coordinates_only`）

| 項目 | 動作 |
|------|------|
| クリック | すべて `ui` の％座標 |
| 到達判定 | 画面テンプレート ＋ ボタン PNG（クリックには使わない） |
| ② MODS | `mods_detect_mode: hybrid` 推奨（画面中央領域 ＋ `join_mods` ボタン） |
| ③-A / ⑥ | 画面未登録時は `cancel_failed` / `accept_network_failure` ボタン PNG |
| ④ / ⑤ | 画面未登録時は `back_empty_list` / `join_game`（2 PNG 試行）ボタン PNG |

## セットアップとの対応

### 最小セットアップ（推奨）

| 項目 | 内容 |
|------|------|
| **ユーザーが撮る画面** | ① サーバー一覧のみ |
| **同梱デフォルト** | CANCEL / BACK / MODS JOIN などのボタン画像（初回に `templates/buttons/` へコピー） |
| **エラー画面キャプチャ** | **不要**（ボタン出現でエラーを検出） |

### フルセットアップ

各画面を個別にキャプチャして同梱デフォルトを上書きできます。

| ステップ | キャプチャファイル | ボタン画像 | サンプル |
|---------|-------------------|-----------|---------|
| ① | `server_list.png` | `buttons/join_server_list.png` | `01_server_list.png` |
| ② | `required_mods.png` | `buttons/join_mods.png` | `02_required_mods.png` |
| ③-A | `connection_failed.png` | `buttons/cancel_failed.png` | `03a_connection_failed.png` |
| ④ | `server_list_empty.png` | `buttons/back_empty_list.png` | — |
| ⑤ | `main_menu.png` | `buttons/join_game.png`（④枚） / `join_game_center.png`（⑤枚） | `04_main_menu_4tiles.png` / `04_main_menu.png` |
| ⑥ | `network_failure.png` | `buttons/accept_network_failure.png` | `05_network_failure.png` |

GUI を起動して **「セットアップ」** ボタンを押す（`python gui.py`）。コマンドラインでの操作は不要です。

## 運用上の注意

- **サブモニター運用:** ARK を表示するモニターを `display.monitor_index` で指定
- **ウィンドウ:** 対象モニター上で ARK が他ウィンドウに隠れないこと
- **解像度変更:** テンプレートとクリック位置の再セットアップが必要
- **操作時:** ARK ウィンドウが一瞬前面に出る（完全バックグラウンド動作ではない）

## 関連ファイル（実装）

| ファイル | 役割 |
|---------|------|
| `src/button_templates.py` | ボタン画像の管理 |
| `src/login_flow.py` | ①〜⑦ の状態機械・リトライ制御 |
| `src/vision.py` | 画面キャプチャ・類似度判定 |
| `src/ui_positions.py` | クリック座標（パーセント → 絶対座標） |
| `src/setup_wizard.py` | テンプレート・座標の登録 |
