param(
    [string]$CodexHome = (Join-Path $HOME ".codex")
)

$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$source = Join-Path $projectRoot "adapters\skills\technical-services-leads"
$destination = Join-Path $CodexHome "skills"
$target = Join-Path $destination "technical-services-leads"

if (-not (Test-Path -LiteralPath (Join-Path $source "SKILL.md"))) {
    throw "Canonical skill not found at $source"
}

New-Item -ItemType Directory -Path $destination -Force | Out-Null

if (Test-Path -LiteralPath $target) {
    $existing = Get-Item -Force -LiteralPath $target
    $targetValue = if ($existing.Target) { [string]$existing.Target } else { "" }
    if ($existing.LinkType -eq "Junction" -and $targetValue -eq $source) {
        Write-Output "Skill junction already installed: $target"
        exit 0
    }
    throw "An existing skill already occupies $target. Remove or rename it before installing this junction."
}

New-Item -ItemType Junction -Path $target -Target $source | Out-Null
Write-Output "Installed skill junction: $target -> $source"
Write-Output "Start a new Codex session so available skills refresh."
