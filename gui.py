"""GUIランチャー（ダブルクリック起動用）"""

from src.windows_environment import enable_per_monitor_dpi_awareness

enable_per_monitor_dpi_awareness()

from src.gui_app import run_gui

if __name__ == "__main__":
    run_gui()
