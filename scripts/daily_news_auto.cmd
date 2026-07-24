@echo off
REM ============================================================
REM 每日新闻自动上传小红书 + 微信 ClawBot 通知
REM 每天 11:00 由 Windows 任务计划程序触发执行
REM ============================================================
setlocal enabledelayedexpansion

set "PROJECT_ROOT=E:\AI\codex\redbook_workflow"
set "PYTHON=%PROJECT_ROOT%\.venv\Scripts\python.exe"
set "CLAWBOT_SCRIPT=%USERPROFILE%\.workbuddy\skills\wechat-clawbot-notify\scripts\send_wechat.py"
set "LOG_DIR=%PROJECT_ROOT%\data\logs"
set "RUN_LOG=%LOG_DIR%\daily_news_auto.log"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo [%date% %time%] ========== Daily News Auto Run START ========== >> "%RUN_LOG%"

REM --- Phase 1: Run redbook_workflow ---
echo [%date% %time%] Phase 1: Running redbook_workflow auto... >> "%RUN_LOG%"
cd /d "%PROJECT_ROOT%"

"%PYTHON%" -m apps.cli auto --title "每日新闻" --keywords "财经产业 公司政策 市场变化 / 国际冲突 外交安全 / 硬科技 芯片 AI" --count 10 --headless --login-hold 0 --wait-timeout 600 >> "%RUN_LOG%" 2>&1
set EXIT_CODE=%ERRORLEVEL%

echo [%date% %time%] Phase 1 complete: exit=%EXIT_CODE% >> "%RUN_LOG%"

REM --- Phase 2: Send WeChat notification ---
echo [%date% %time%] Phase 2: Sending WeChat notification... >> "%RUN_LOG%"

if %EXIT_CODE% EQU 0 (
    set "MSG=✅ 每日新闻上传完成 [%date%] 请到小红书创作者中心草稿箱查看并发布。"
) else (
    set "MSG=❌ 每日新闻运行异常 [%date%] 退出码=%EXIT_CODE%，请检查日志：%RUN_LOG%"
)

REM Use managed Python to call ClawBot notification
"C:\Users\30527\.workbuddy\binaries\python\versions\3.13.12\python.exe" "%CLAWBOT_SCRIPT%" send "!MSG!" >> "%RUN_LOG%" 2>&1

echo [%date% %time%] ========== Daily News Auto Run END ========== >> "%RUN_LOG%"
exit /b %EXIT_CODE%
