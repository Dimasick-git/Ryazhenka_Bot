param(
    [string]$Token
)

if (-not $Token) {
    $Token = Read-Host "Введите BOT_TOKEN (скопируйте из безопасного места)"
}

$envPath = Join-Path -Path (Get-Location) -ChildPath ".env"

# Write or update BOT_TOKEN line
if (Test-Path $envPath) {
    $content = Get-Content $envPath -Raw
    if ($content -match 'BOT_TOKEN\s*=') {
        $new = $content -replace 'BOT_TOKEN\s*=.*', "BOT_TOKEN=\"$Token\""
        Set-Content -Path $envPath -Value $new -Encoding UTF8
        Write-Host "Обновлён .env с новым BOT_TOKEN"
    } else {
        Add-Content -Path $envPath -Value "BOT_TOKEN=\"$Token\""
        Write-Host "Добавлен BOT_TOKEN в .env"
    }
} else {
    "BOT_TOKEN=\"$Token\"`n" | Out-File -FilePath $envPath -Encoding UTF8
    Write-Host ".env создан и BOT_TOKEN записан"
}

Write-Host "Готово. Не забудьте добавить .env в .gitignore если хотите скрыть токен от коммитов."
