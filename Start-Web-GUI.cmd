@echo off
setlocal
cd /d "%~dp0"
if not exist "frontend\dist\index.html" (
  echo React GUI not built. Run: cd frontend ^&^& npm ci ^&^& npm run build
  pause
  exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$url='http://127.0.0.1:8765'; try { $response=Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 1; if ($response.StatusCode -eq 200) { Start-Process $url; exit 0 } } catch {}; exit 1"
if not errorlevel 1 exit /b 0
".venv\Scripts\python.exe" -m apps.web_gui --open-browser %*
endlocal
