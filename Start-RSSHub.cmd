@echo off
rem Start RSSHub on demand (http://127.0.0.1:1200) and keep this window open.
rem Nothing is installed to C: and nothing autostarts with Windows.
set COREPACK_ENABLE_DOWNLOAD_PROMPT=0
set NODE_ENV=production
set LISTEN_INADDR_ANY=0
cd /d "%~dp0tools\RSSHub"
if errorlevel 1 exit /b 1

rem Build once if the dist output is missing (first run after clone/pull).
if not exist dist\index.mjs (
  echo RSSHub build is missing. Run scripts\provision_local_tools.ps1 first.
  exit /b 1
)

echo Starting RSSHub at http://127.0.0.1:1200 (press Ctrl+C to stop)
node dist/index.mjs
