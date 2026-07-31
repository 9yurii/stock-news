@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo.
echo   docs 폴더를 로컬에서 미리 봅니다...
echo   (실제 사이트는 GitHub Pages 주소에서 열립니다)
echo.
python -m stock_manager.web
if errorlevel 1 (
    echo.
    echo   [오류] 실행에 실패했습니다.
    echo   파이썬이 설치되어 있는지 확인해 주세요: python --version
    echo.
    pause
)
