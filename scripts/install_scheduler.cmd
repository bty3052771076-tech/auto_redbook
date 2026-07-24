@echo off
REM 一键创建 Windows 定时任务：每天 11:00 执行每日新闻自动上传
REM 需要以管理员身份运行此脚本

set TASK_NAME=RedbookDailyNews
set SCRIPT_PATH=E:\AI\codex\redbook_workflow\scripts\daily_news_auto.ps1

echo ============================================
echo  创建每日新闻自动任务
echo  名称: %TASK_NAME%
echo  时间: 每天 11:00
echo  脚本: %SCRIPT_PATH%
echo ============================================
echo.

REM 先删除旧任务
schtasks /Delete /TN "%TASK_NAME%" /F 2>nul

REM 创建新任务
schtasks /Create /TN "%TASK_NAME%" /SC DAILY /ST 11:00 /F /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \"%SCRIPT_PATH%\""

if %ERRORLEVEL% EQU 0 (
    echo.
    echo [OK] 任务创建成功!
    echo.
    echo 验证任务:
    schtasks /Query /TN "%TASK_NAME%" /FO LIST | findstr /C:"TaskName" /C:"Schedule" /C:"Start Time"
) else (
    echo.
    echo [FAIL] 任务创建失败。请右键此文件 -> 以管理员身份运行。
)

pause
