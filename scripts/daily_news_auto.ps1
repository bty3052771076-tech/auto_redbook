# Daily News Auto Upload to Xiaohongshu + WeChat ClawBot Notification
# 每日新闻自动上传小红书草稿箱，并通过微信 ClawBot 发送通知（含所有标题）
# Scheduled via Windows Task Scheduler: daily at 11:00 AM Beijing Time

$ErrorActionPreference = "Continue"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path "$ScriptDir\.."
$PythonExe = "$ProjectRoot\.venv\Scripts\python.exe"
$ClawBotScript = "$env:USERPROFILE\.workbuddy\skills\wechat-clawbot-notify\scripts\send_wechat.py"
$ClawBotPython = "$env:USERPROFILE\.workbuddy\binaries\python\versions\3.13.12\python.exe"
$LogDir = "$ProjectRoot\data\logs"
$RunLog = "$LogDir\daily_news_auto.log"

if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

function Write-Log {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "$timestamp | $Message"
    Add-Content -Path $RunLog -Value $line -Encoding UTF8
    Write-Host $line
}

function Send-ClawBotNotification {
    param([string]$Message)
    try {
        $result = & $ClawBotPython "$ClawBotScript" send "$Message" 2>&1
        $exitCode = $LASTEXITCODE
        Write-Log "ClawBot exit=$exitCode"
        return ($exitCode -eq 0)
    } catch {
        Write-Log "ClawBot error: $_"
        return $false
    }
}

Write-Log "========== Daily News Auto Run START =========="
$startTime = Get-Date

try {
    Set-Location $ProjectRoot

    $keywords = "财经产业 公司政策 市场变化 / 国际冲突 外交安全 / 硬科技 芯片 AI"
    $arguments = @(
        "-m", "apps.cli", "auto",
        "--title", "每日新闻",
        "--keywords", $keywords,
        "--count", "10",
        "--headless",
        "--login-hold", "0",
        "--wait-timeout", "600"
    )

    Write-Log "Command: $PythonExe $($arguments -join ' ')"
    $output = & $PythonExe $arguments 2>&1
    $exitCode = $LASTEXITCODE
    $duration = [math]::Round(((Get-Date) - $startTime).TotalMinutes, 1)

    # Parse results
    $savedList = @()
    $failedList = @()

    foreach ($line in $output) {
        Write-Log "  $line"

        # Extract title from lines like: - post_id=xxx | 标题：xxx
        if ($line -match 'post_id=\S+\s*\|\s*标题[：:]\s*(.+)$') {
            $title = $Matches[1].Trim()
            # Will be matched to result later
        }

        # Match result lines: post_id=xxx result: saved_draft
        if ($line -match 'post_id=(\S+)\s+result:\s*(\S+)') {
            $postId = $Matches[1]
            $result = $Matches[2]
            if ($result -eq 'saved_draft') {
                $savedList += $postId
            } elseif ($result -eq 'failed') {
                $failedList += $postId
            }
        }
    }

    # Get titles from post.json files
    $savedTitles = @()
    $failedTitles = @()

    foreach ($postId in $savedList) {
        $jsonPath = "$ProjectRoot\data\posts\$postId\post.json"
        if (Test-Path $jsonPath) {
            try {
                $post = Get-Content $jsonPath -Raw -Encoding UTF8 | ConvertFrom-Json
                $title = $post.title
                if ($title) { $savedTitles += $title }
            } catch {}
        }
    }

    foreach ($postId in $failedList) {
        $jsonPath = "$ProjectRoot\data\posts\$postId\post.json"
        if (Test-Path $jsonPath) {
            try {
                $post = Get-Content $jsonPath -Raw -Encoding UTF8 | ConvertFrom-Json
                $title = $post.title
                if ($title) { $failedTitles += $title }
            } catch {}
        }
    }

    $savedCount = $savedList.Count
    $failedCount = $failedList.Count

    Write-Log "Phase 1 complete: exit=$exitCode, duration=${duration}min, saved=$savedCount, failed=$failedCount"

    # Build notification message
    $dateStr = Get-Date -Format "MM-dd"
    $notifyMsg = ""

    if ($savedCount -ge 1) {
        $notifyMsg += "✅ 每日新闻 [$dateStr] ${savedCount}/10条已保存草稿`n耗时: ${duration}分钟`n`n"
        $notifyMsg += "━━ 已保存 ━━`n"
        for ($i = 0; $i -lt $savedTitles.Count; $i++) {
            $notifyMsg += "$($i+1). $($savedTitles[$i])`n"
        }
    }

    if ($failedCount -ge 1) {
        $notifyMsg += "`n━━ 失败 ━━`n"
        for ($i = 0; $i -lt $failedTitles.Count; $i++) {
            $notifyMsg += "❌ $($failedTitles[$i])`n"
        }
    }

    if ($savedCount -eq 0 -and $failedCount -eq 0) {
        $notifyMsg = "❌ 每日新闻 [$dateStr] 运行异常`n退出码: $exitCode | 耗时: ${duration}分钟`n请检查日志: $RunLog"
    }

    Write-Log "Notification: $notifyMsg"
    Send-ClawBotNotification -Message $notifyMsg

} catch {
    $duration = [math]::Round(((Get-Date) - $startTime).TotalMinutes, 1)
    Write-Log "FATAL ERROR: $_"
    $failMsg = "❌ 每日新闻运行崩溃 [$((Get-Date).ToString('MM-dd'))]`n错误: $_"
    Send-ClawBotNotification -Message $failMsg
}

Write-Log "========== Daily News Auto Run END =========="
