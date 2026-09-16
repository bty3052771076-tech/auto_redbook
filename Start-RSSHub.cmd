@echo off
rem Start RSSHub on demand (http://127.0.0.1:1200) and keep this window open.
rem Nothing is installed to C: and nothing autostarts with Windows.
set COREPACK_ENABLE_DOWNLOAD_PROMPT=0
set PATH=E:\AI\tools\pnpm-bin;%PATH%
cd /d E:\AI\tools\RSSHub

rem Build once if the dist output is missing (first run after clone/pull).
if not exist dist\index.mjs (
  echo First run: building RSSHub...
  call pnpm build
)

echo Starting RSSHub at http://127.0.0.1:1200 (press Ctrl+C to stop)
node dist/index.mjs
