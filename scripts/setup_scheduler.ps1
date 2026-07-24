# ============================================================
# 一键配置 Windows 任务计划程序
# 以管理员身份运行此脚本
# ============================================================
$taskName = "RedbookDailyNews"
$scriptPath = "E:\AI\codex\redbook_workflow\scripts\daily_news_auto.cmd"
$description = "每日 11:00 自动生成10条新闻并上传小红书草稿箱，完成后通过微信 ClawBot 通知"

Write-Host "正在配置每日新闻自动任务..."
Write-Host "任务名称: $taskName"
Write-Host "执行时间: 每天 11:00"
Write-Host "执行脚本: $scriptPath"
Write-Host ""

# 删除已有任务
schtasks /Delete /TN $taskName /F 2>$null

# 创建新任务
$action = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command `"Start-Process cmd.exe -ArgumentList '/c', '$scriptPath' -WindowStyle Hidden`""
$createResult = schtasks /Create /TN $taskName /TR $action /SC DAILY /ST 11:00 /F 2>&1

if ($LASTEXITCODE -eq 0) {
    Write-Host "[OK] 任务 '$taskName' 创建成功！"
    Write-Host ""
    Write-Host "任务信息："
    schtasks /Query /TN $taskName /FO LIST 2>&1 | Select-String -Pattern "TaskName|Schedule|Start Time|Status"
} else {
    Write-Host "[FAIL] 任务创建失败：$createResult"
    Write-Host ""
    Write-Host "请手动创建："
    Write-Host "1. 打开 任务计划程序 (taskschd.msc)"
    Write-Host "2. 创建基本任务 -> 名称: RedbookDailyNews"
    Write-Host "3. 触发器: 每天, 11:00"
    Write-Host "4. 操作: 启动程序 -> $scriptPath"
}
