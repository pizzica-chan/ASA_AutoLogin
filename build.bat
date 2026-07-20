@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo   ASA_Login 配布物ビルド
echo ========================================
echo.

where python >nul 2>&1
if %errorlevel%==0 (
    python build.py
    goto :done
)

where py >nul 2>&1
if %errorlevel%==0 (
    py build.py
    goto :done
)

echo [エラー] Python が見つかりません。
echo Python 3.10 以上をインストールしてから再実行してください。
pause
exit /b 1

:done
if %errorlevel% neq 0 (
    echo.
    echo [エラー] ビルドに失敗しました。
    pause
    exit /b %errorlevel%
)

echo.
echo 完了: dist\ASA_Login\ と release\ASA_Login-win64.zip
pause
