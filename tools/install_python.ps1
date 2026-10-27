#requires -version 3.0
<#
  CardForge 启动助手 / startup helper
  ==================================================================
  什么时候会跑到这里 / when this runs
    启动.bat 在自己找不到「能真正执行的 Python 3.10+」时调用本脚本。
    典型情况：目标电脑根本没装 Python；或者 PATH 里命中的是 Windows
    自带的「应用执行别名」（Microsoft Store 版 Python 被卸载/损坏后留下的
    空壳）—— 执行它会直接报「系统无法执行指定的程序」。

  它会做什么 / what it does
    1. 再认真找一遍已装的 Python（含 py 启动器、venv、常见安装目录）。
    2. 找不到时给出中英双语菜单：
         [1] 自动安装 Python 3.12（只装到当前用户，不需要管理员）
         [2] 打开 python.org 下载页手动安装
         [3] 退出
    3. 自动安装：优先国内镜像（npmmirror → 华为云 → 阿里云 → python.org），
       校验官方 MD5 + Authenticode 签名（Python Software Foundation）后才运行；
       winget 作为最后的兜底。
    4. 安装完复验一遍，成功退出码 0；失败 1；用户退出 2。

  注意 / notes
    * 不会修改系统级设置；安装目录在 %LOCALAPPDATA%\Programs\Python\Python312
    * -DryRun 只打印计划，不下载、不安装（用于自测）
    * -DownloadOnly 只下载并校验安装包，不安装（用于预先缓存 / 排查网络）
    * -Yes 跳过菜单，直接走自动安装（用于自动化）
  ==================================================================
#>
[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$Yes,
    [switch]$DownloadOnly
)

$ErrorActionPreference = 'Stop'

# 控制台编码：启动.bat 已 chcp 65001；单独双击本脚本时也补一次。
try { & chcp.com 65001 > $null } catch {}
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false) } catch {}

$ScriptDir = $PSScriptRoot
$Root = Split-Path -Parent $ScriptDir
$PythonVersion = '3.12.10'
$AliasPath = $null
if ($env:LOCALAPPDATA) {
    $AliasPath = Join-Path $env:LOCALAPPDATA 'Microsoft\WindowsApps\python.exe'
}
$script:AliasBroken = $false
$ExitOk = 0
$ExitFail = 1
$ExitCancel = 2

function Say([string]$Text = '') { Write-Host $Text }
function SayCN([string]$Cn, [string]$En) { Write-Host ("  " + $Cn + "  / " + $En) }

function Show-Header {
    Say ''
    Say '  ============================================================'
    Say '   CardForge 启动助手 / startup helper'
    Say '  ============================================================'
    Say ''
}

function Show-Goodbye([int]$Code) {
    Say ''
    exit $Code
}

# ------------------------------------------------------------------
#  探测：只认「真的能跑起来且 >= 3.10」的解释器
# ------------------------------------------------------------------
function Test-PythonExe {
    param(
        [string]$Exe,
        [string[]]$Prefix = @()
    )
    if (-not $Exe) { return $null }
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        # PowerShell 5.1 mangles embedded double quotes when calling native exes,
        # so the Python snippet uses single quotes only.
        $code = "import sys; print('.'.join(map(str, sys.version_info[:3]))); raise SystemExit(0 if sys.version_info >= (3,10) else 3)"
        $argv = @()
        $argv += $Prefix
        $argv += @('-c', $code)
        $out = & $Exe @argv 2>$null
        $exitCode = $LASTEXITCODE
        if ($exitCode -eq 0 -and $out) {
            $ver = [string]($out | Select-Object -Last 1)
            if ($ver) {
                return [pscustomobject]@{
                    Exe     = $Exe
                    Prefix  = $Prefix
                    Version = $ver.Trim()
                    Label   = (@($Exe) + $Prefix) -join ' '
                }
            }
        }
    } catch {
        return $null
    } finally {
        $ErrorActionPreference = $prevEap
    }
    return $null
}

function Join-Safe {
    param([string]$Base, [string]$Child)
    if ($Base) { return (Join-Path $Base $Child) }
    return $null
}

function Get-PythonCandidates {
    $list = New-Object System.Collections.ArrayList

    if ($env:CARDFORGE_PYTHON) {
        [void]$list.Add([pscustomobject]@{ Exe = $env:CARDFORGE_PYTHON; Prefix = @() })
    }

    $venv = Join-Safe $Root '.venv\Scripts\python.exe'
    if ($venv -and (Test-Path $venv)) {
        [void]$list.Add([pscustomobject]@{ Exe = $venv; Prefix = @() })
    }

    $pyCmd = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($pyCmd) {
        foreach ($v in @('-3.13', '-3.12', '-3.11', '-3.10', '-3')) {
            [void]$list.Add([pscustomobject]@{ Exe = $pyCmd.Source; Prefix = @($v) })
        }
    }

    foreach ($name in @('python', 'python3')) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd -and $cmd.Source) {
            [void]$list.Add([pscustomobject]@{ Exe = $cmd.Source; Prefix = @() })
        }
    }

    $patterns = @(
        (Join-Safe $env:LOCALAPPDATA 'Programs\Python\Python3*\python.exe'),
        (Join-Safe $env:APPDATA 'uv\python\cpython-3*\python.exe'),
        (Join-Safe $env:ProgramFiles 'Python3*\python.exe'),
        (Join-Safe $env:ProgramFiles 'Python\Python3*\python.exe'),
        (Join-Safe ${env:ProgramFiles(x86)} 'Python3*\python.exe'),
        'C:\Python3*\python.exe',
        (Join-Safe $env:USERPROFILE 'anaconda3\python.exe'),
        (Join-Safe $env:USERPROFILE 'miniconda3\python.exe'),
        (Join-Safe $env:ProgramData 'anaconda3\python.exe'),
        (Join-Safe $env:ProgramData 'miniconda3\python.exe'),
        (Join-Safe $env:USERPROFILE 'scoop\apps\python\current\python.exe'),
        $AliasPath
    ) | Where-Object { $_ }
    foreach ($pat in $patterns) {
        try {
            Get-Item $pat -ErrorAction SilentlyContinue | ForEach-Object {
                [void]$list.Add([pscustomobject]@{ Exe = $_.FullName; Prefix = @() })
            }
        } catch {}
    }

    return $list
}

function Find-Python {
    foreach ($c in (Get-PythonCandidates)) {
        $hit = Test-PythonExe -Exe $c.Exe -Prefix $c.Prefix
        if ($hit) { return $hit }
        if ($AliasPath -and $c.Exe -eq $AliasPath) { $script:AliasBroken = $true }
    }
    return $null
}

function Update-PathFromRegistry {
    try {
        $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
        $user = [Environment]::GetEnvironmentVariable('Path', 'User')
        if ($machine -or $user) {
            $env:Path = (@($machine, $user) | Where-Object { $_ }) -join ';'
        }
    } catch {}
}

# ------------------------------------------------------------------
#  安装包：架构、文件名、官方 MD5
# ------------------------------------------------------------------
function Get-InstallerInfo {
    $arch = $env:PROCESSOR_ARCHITECTURE
    $isArm = ($arch -eq 'ARM64') -or ($env:PROCESSOR_ARCHITEW6432 -eq 'ARM64')
    if ($isArm) {
        return [pscustomobject]@{
            Name = "python-$PythonVersion-arm64.exe"
            Md5  = '37df52717faa6c514342b8d43cae7026'
            Kind = 'ARM64'
        }
    }
    if ([Environment]::Is64BitOperatingSystem) {
        return [pscustomobject]@{
            Name = "python-$PythonVersion-amd64.exe"
            Md5  = '5eddb0b6f12c852725de071ae681dde4'
            Kind = '64-bit'
        }
    }
    return [pscustomobject]@{
        Name = "python-$PythonVersion.exe"
        Md5  = 'ff3e7e2582811ade44916d9c3d2a64b2'
        Kind = '32-bit'
    }
}

function Test-InstallerFile {
    param(
        [string]$Path,
        [string]$Md5
    )
    if (-not (Test-Path $Path)) { return $false }
    $item = Get-Item $Path
    if ($item.Length -lt 15000000) { return $false }

    $hashOk = $false
    try {
        if (Get-Command Get-FileHash -ErrorAction SilentlyContinue) {
            $actual = (Get-FileHash -Path $Path -Algorithm MD5).Hash.ToLowerInvariant()
            $hashOk = ($actual -eq $Md5.ToLowerInvariant())
            if (-not $hashOk) { return $false }
        }
    } catch {
        return $false
    }

    try {
        $sig = Get-AuthenticodeSignature -FilePath $Path
        if ($sig.Status -eq 'NotSigned' -or $sig.Status -eq 'HashMismatch') { return $false }
        if ($sig.SignerCertificate -and ($sig.SignerCertificate.Subject -notmatch 'Python Software Foundation')) {
            return $false
        }
    } catch {
        # 没有 Authenticode 能力（极老的系统）时，至少 MD5 已经核对过
        return $hashOk
    }
    return $true
}

function Get-InstallerFile {
    param([pscustomobject]$Info)

    $dst = Join-Path $env:TEMP $Info.Name
    if (Test-InstallerFile -Path $dst -Md5 $Info.Md5) {
        Say ("  已缓存安装包 / using cached installer: " + $dst)
        return $dst
    }
    if (Test-Path $dst) { Remove-Item $dst -Force -ErrorAction SilentlyContinue }

    $bases = @(
        "https://registry.npmmirror.com/-/binary/python/$PythonVersion",
        "https://mirrors.huaweicloud.com/python/$PythonVersion",
        "https://mirrors.aliyun.com/python-release/windows",
        "https://www.python.org/ftp/python/$PythonVersion"
    )

    foreach ($base in $bases) {
        $url = "$base/$($Info.Name)"
        Say ''
        Say ("  下载 / downloading: " + $url)
        if ($DryRun) {
            Say ("  DRYRUN: would save to " + $dst + " and verify MD5 " + $Info.Md5)
            return $null
        }
        try {
            if (Get-Command curl.exe -ErrorAction SilentlyContinue) {
                # -s: no progress on stderr (PowerShell 5.1 can turn native stderr
                #     into a terminating error); we print our own message above.
                & curl.exe -L --fail --retry 2 --connect-timeout 15 -s -o $dst $url 2>$null
            } else {
                Invoke-WebRequest -Uri $url -OutFile $dst -UseBasicParsing -TimeoutSec 900
            }
            if (Test-InstallerFile -Path $dst -Md5 $Info.Md5) {
                Say '  下载完成，校验通过 / download verified.'
                return $dst
            }
            Say '  [!] 校验没通过，换下一个源 / checksum mismatch, trying next mirror.'
            Remove-Item $dst -Force -ErrorAction SilentlyContinue
        } catch {
            Say ("  [!] " + $_.Exception.Message)
            if (Test-Path $dst) { Remove-Item $dst -Force -ErrorAction SilentlyContinue }
        }
    }
    return $null
}

# ------------------------------------------------------------------
#  安装
# ------------------------------------------------------------------
function Install-PythonExe {
    param([string]$Installer)

    Say ''
    Say ("  安装到当前用户 / installing for current user: " + $env:LOCALAPPDATA + "\Programs\Python")
    $argList = @(
        '/quiet',
        'InstallAllUsers=0',
        'PrependPath=1',
        'Include_launcher=1',
        'Include_pip=1',
        'Include_test=0',
        'Include_doc=0',
        'Include_tcltk=1'
    )
    if ($DryRun) {
        Say ("  DRYRUN: " + $Installer + " " + ($argList -join ' '))
        return $false
    }
    $proc = Start-Process -FilePath $Installer -ArgumentList $argList -Wait -PassThru
    Say ("  安装程序退出码 / installer exit code: " + $proc.ExitCode)
    return ($proc.ExitCode -eq 0 -or $proc.ExitCode -eq 3010)
}

function Install-WithWinget {
    $wg = Get-Command winget.exe -ErrorAction SilentlyContinue
    if (-not $wg) { return $false }
    Say ''
    Say '  尝试 winget（最后兜底）/ trying winget as a last resort...'
    $argList = @(
        'install', '--id', 'Python.Python.3.12', '-e',
        '--scope', 'user', '--silent', '--disable-interactivity',
        '--accept-package-agreements', '--accept-source-agreements'
    )
    if ($DryRun) {
        Say ("  DRYRUN: winget " + ($argList -join ' '))
        return $false
    }
    try {
        & $wg.Source @argList | Out-Host
    } catch {
        Say ("  [!] winget: " + $_.Exception.Message)
        return $false
    }
    Update-PathFromRegistry
    return [bool](Find-Python)
}

function Show-ManualHelp {
    Say ''
    Say '  手动安装 / manual setup:'
    Say '    1. 打开 / open  https://www.python.org/downloads/windows/'
    Say '    2. 安装时勾选 / tick "Add python.exe to PATH"'
    Say '    3. 回到 CardForge 文件夹，重新双击 启动.bat / re-run the launcher'
    Say ''
}

# ==================================================================
#  main
# ==================================================================
Show-Header

$existing = Find-Python
if ($existing) {
    Say ("  已找到可用 Python / Python is ready: " + $existing.Version)
    Say ("  " + $existing.Label)
    Show-Goodbye $ExitOk
}

$aliasNote = ''
if ($script:AliasBroken) {
    $aliasNote = 'Windows 的应用执行别名（Microsoft Store 版 Python 的快捷方式）存在但无法启动；'
    $aliasNote += '不影响下面的自动安装。'
}

$os = [Environment]::OSVersion.Version
if ($os.Major -lt 6 -or ($os.Major -eq 6 -and $os.Minor -lt 3)) {
    Say '  [X] 这台电脑的系统太旧 / Windows is too old.'
    Say '      Python 3.10+ 需要 Windows 8.1 或更高 / needs Windows 8.1 or newer.'
    Show-Goodbye $ExitFail
}

$info = Get-InstallerInfo
Say '  没有找到能用的 Python 3.10+ / no usable Python 3.10+ was found.'
if ($aliasNote) { Say ('  [!] ' + $aliasNote) }
Say ''
Say '  可以现在自动装一个 / CardForge can install one now:'
Say ('    * Python ' + $PythonVersion + '（只装到当前用户，不需要管理员 / per-user, no admin）')
Say ('    * ' + $info.Kind + ' 安装包，约 25 MB，来源：npmmirror / 华为云 / 阿里云 / python.org')
Say ''
Say '  [1] 自动安装 / install automatically   (推荐 / recommended)'
Say '  [2] 打开下载页，我自己装 / open the download page'
Say '  [3] 退出 / quit'
Say ''

$choice = '1'
if (-not $Yes) {
    try {
        $answer = Read-Host '  选择 / choose [1/2/3]（直接回车 = 1）'
        if ($answer) { $choice = $answer.Trim() }
    } catch {
        $choice = '3'
    }
}

if ($choice -eq '2') {
    try { Start-Process 'https://www.python.org/downloads/windows/' } catch {}
    Show-ManualHelp
    Show-Goodbye $ExitCancel
}
if ($choice -ne '1') {
    Say '  已退出 / cancelled.'
    Show-Goodbye $ExitCancel
}

if ($DryRun) {
    Say ''
    Say ('  DRYRUN plan: ' + $info.Name + ' (MD5 ' + $info.Md5 + ')')
    [void](Get-InstallerFile -Info $info)
    Show-Goodbye $ExitOk
}

$installer = $null
try {
    $installer = Get-InstallerFile -Info $info
} catch {
    Say ("  [!] 下载失败 / download failed: " + $_.Exception.Message)
}

if ($DownloadOnly) {
    if ($installer) {
        Say ''
        Say ('  [OK] 已下载并通过校验 / downloaded and verified: ' + $installer)
        Show-Goodbye $ExitOk
    }
    Say '  [X] 下载或校验失败 / download or verification failed.'
    Show-Goodbye $ExitFail
}

$installed = $false
if ($installer) {
    $installed = Install-PythonExe -Installer $installer
}

Update-PathFromRegistry
$found = Find-Python
if ($installed -and $found) {
    Say ''
    Say ("  [OK] Python " + $found.Version + " 已就绪 / is ready.")
    Say ("       " + $found.Label)
    Show-Goodbye $ExitOk
}

if (-not $installed) {
    Say ''
    Say '  安装包方式没有完成，尝试 winget / installer route failed, trying winget...'
    if (Install-WithWinget) {
        Update-PathFromRegistry
        $found = Find-Python
        if ($found) {
            Say ''
            Say ("  [OK] Python " + $found.Version + " 已就绪 / is ready.")
            Show-Goodbye $ExitOk
        }
    }
}

Say ''
Say '  [X] 自动安装没有成功 / automatic setup failed.'
Say '      安装日志一般在 / installer logs are usually in:'
Say ('        ' + (Join-Path $env:TEMP 'Python ' + $PythonVersion + '*_log.txt'))
Show-ManualHelp
Show-Goodbye $ExitFail
