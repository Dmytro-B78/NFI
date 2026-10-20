# Persist blacklist_scout permanent blocks into user_data/blacklist-binance.json.
#
# Usage (local repo, PowerShell):
#   .\scripts\persist_blacklist.ps1 CYS BR
#
# Adds one "(BASE)/.*" entry per ticker at the top of pair_blacklist, then
# guards: file clean before, tickers not yet blocked by any pattern, valid
# JSON, entry count +N, git diff exactly N/0 - then commits only this file and
# pushes. On the server afterwards: git pull (no restart needed, the pairs are
# already blocked in the running bot by blacklist_scout).
param(
  [Parameter(Mandatory = $true, ValueFromRemainingArguments = $true)]
  [string[]]$Bases
)
$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
$rel = "user_data/blacklist-binance.json"
$path = Join-Path $repo "user_data\blacklist-binance.json"
$py = if (Get-Command python -ErrorAction SilentlyContinue) { "python" } else { "python3" }

$Bases = @($Bases | ForEach-Object { $_.Trim().ToUpper() } | Where-Object { $_ } | Select-Object -Unique)
foreach ($b in $Bases) {
  if ($b -notmatch '^[A-Z0-9]+$') { throw "Bad ticker '$b' (only A-Z and 0-9)." }
}
$n = $Bases.Count

Set-Location $repo
if (git status --porcelain -- $rel) { throw "$rel has uncommitted edits. Stop." }

# Count entries and check every ticker is not blocked yet (same fullmatch rule as freqtrade)
$check = "import json,re,sys; d=json.load(open(sys.argv[1], encoding='utf-8'))['exchange']['pair_blacklist']; " +
  "hit=[b for b in sys.argv[2:] if any(re.fullmatch(p, b + '/USDT:USDT') for p in d)]; " +
  "print(len(d)); print(' '.join(hit))"
$out = & $py -c $check $path @Bases
if ($LASTEXITCODE -ne 0) { throw "Cannot read $rel. Stop." }
$before = [int]$out[0]
if ($out.Count -gt 1 -and $out[1].Trim()) { throw "Already blocked by the file: $($out[1]). Stop." }

$raw = [System.IO.File]::ReadAllText($path)
$nl = if ($raw.Contains("`r`n")) { "`r`n" } else { "`n" }
$anchor = '"pair_blacklist": [' + $nl
if (([regex]::Matches($raw, [regex]::Escape($anchor))).Count -ne 1) { throw 'Anchor for pair_blacklist count != 1. Stop.' }
$insert = ($Bases | ForEach-Object { '      "(' + $_ + ')/.*",' + $nl }) -join ''
[System.IO.File]::WriteAllText($path, $raw.Replace($anchor, $anchor + $insert), (New-Object System.Text.UTF8Encoding($false)))

$after = & $py -c "import json,sys; print(len(json.load(open(sys.argv[1], encoding='utf-8'))['exchange']['pair_blacklist']))" $path
if ($LASTEXITCODE -ne 0) { git checkout -- $rel; throw "JSON invalid after edit - file restored. Stop." }
if ([int]$after -ne $before + $n) { git checkout -- $rel; throw "Entries $before -> $after, expected +$n - file restored. Stop." }
$ns = (git diff --numstat -- $rel) -split "`t"
if (($ns[0] -ne "$n") -or ($ns[1] -ne "0")) { git checkout -- $rel; throw "git diff $($ns[0])/$($ns[1]) != $n/0 - file restored. Stop." }

git diff --stat -- $rel
git add $rel
git commit -m "blacklist: persist $($Bases -join ', ') (blacklist_scout)" `
  -m "Permanent entries recommended by scripts/blacklist_scout.py; already blocked at runtime in the bot. $before -> $after entries."
if ($LASTEXITCODE -ne 0) { throw "git commit failed." }
git push
if ($LASTEXITCODE -ne 0) { throw "git push failed - commit is local only." }
Write-Host "Done: $before -> $after entries. On the server: cd /home/ubuntu/NFI && git pull (no restart needed)."
