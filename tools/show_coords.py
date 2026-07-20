"""マウスカーソル座標をリアルタイム表示（セットアップ補助）"""

import time

import pydirectinput

print("マウス座標を表示中... (Ctrl+C で終了)")
print()

try:
    while True:
        x, y = pydirectinput.position()
        print(f"\r  X: {x:5d}  Y: {y:5d}", end="", flush=True)
        time.sleep(0.5)
except KeyboardInterrupt:
    print("\n終了しました。")
