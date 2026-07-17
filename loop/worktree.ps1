# MemoAlign 循环工程：隔离 worktree 助手
# 用法：在仓库根目录运行
#   pwsh loop/worktree.ps1            # 新建一个以日期命名的隔离 worktree + 分支
#   pwsh loop/worktree.ps1 -Clean     # 列出并清理已合并的 loop worktree
param(
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$Stamp = Get-Date -Format "yyyyMMdd-HHmm"
$Branch = "loop/$Stamp"
$Path = Join-Path $PSScriptRoot ".." ".." "memoalign-loop-$Stamp"

if ($Clean) {
    Write-Host "=== 清理已合并的 loop worktree ==="
    git worktree list
    $wt = git worktree list --porcelain | Where-Object { $_ -match '^worktree ' } | ForEach-Object { $_.Substring(9) }
    foreach ($w in $wt) {
        if ($w -like "*memoalign-loop-*") {
            Write-Host "prune: $w"
            git worktree remove --force $w 2>$null
        }
    }
    git worktree prune
    exit 0
}

Write-Host "=== 新建隔离 worktree: $Branch @ $Path ==="
git worktree add $Path -b $Branch
Write-Host "已创建。进入后执行迭代："
Write-Host "  cd $Path"
Write-Host "  # 按 SKILL.md 迭代协议执行 -> 验证 -> 推送"
