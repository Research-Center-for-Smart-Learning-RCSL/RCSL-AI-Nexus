Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:CodexPackageName = 'OpenAI.Codex'
$script:CodexStoreId = '9PLM9XGG6VKS'
$script:DefaultGatewayBaseUrl = 'https://llmapi.rcsl.online'
$script:DefaultCapability = 'code'
$script:ManagedProviderId = 'rcsl_nexus_switcher'
$script:SwitcherMutexName = 'Local\RCSL.AI.Nexus.CodexAppSwitcher'
$script:StateSchemaVersion = 2

# A TOML key segment is a bare key, a basic string, or a literal string. The App
# writes all three -- `[projects.'c:\path']` and `[plugins."name@source"]` are its
# normal output -- so header parsing has to accept quoting rather than refuse it.
$script:TomlKeySegmentPattern = '(?:[A-Za-z0-9_-]+|"(?:[^"\\]|\\.)*"|' + "'[^']*'" + ')'
$script:TomlKeyPathPattern = '{0}(?:\s*\.\s*{0})*' -f $script:TomlKeySegmentPattern
$script:TomlTableHeaderPattern = '^\s*\[\s*({0})\s*\]\s*(?:#.*)?$' -f $script:TomlKeyPathPattern
$script:TomlArrayTableHeaderPattern = '^\s*\[\[\s*({0})\s*\]\]\s*(?:#.*)?$' -f $script:TomlKeyPathPattern
$script:TomlQuotedKeyPattern = '^\s*(?:"(?:[^"\\]|\\.)*"|' + "'[^']*'" + ')\s*(?:\.|=)'

function Assert-Windows {
    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
        throw 'The Codex App switcher supports Windows only.'
    }
}

function Get-CodexHomePath {
    $configured = [Environment]::GetEnvironmentVariable('CODEX_HOME', 'Process')
    if ([string]::IsNullOrWhiteSpace($configured)) {
        $configured = [Environment]::GetEnvironmentVariable('CODEX_HOME', 'User')
    }
    if ([string]::IsNullOrWhiteSpace($configured)) {
        return (Join-Path $env:USERPROFILE '.codex')
    }
    return [Environment]::ExpandEnvironmentVariables($configured)
}

function Get-CodexConfigPath {
    return (Join-Path (Get-CodexHomePath) 'config.toml')
}

function Get-SwitcherStateDirectory {
    $root = Join-Path $env:LOCALAPPDATA 'RCSL-AI-Nexus'
    return (Join-Path $root 'codex-app-switcher')
}

function Get-SwitcherStatePath {
    return (Join-Path (Get-SwitcherStateDirectory) 'state.json')
}

function New-DirectoryIfMissing {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        [void](New-Item -ItemType Directory -Path $Path -Force)
    }
}

function Protect-SwitcherStateDirectory {
    $path = Get-SwitcherStateDirectory
    New-DirectoryIfMissing -Path $path
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $security = New-Object Security.AccessControl.DirectorySecurity
    $security.SetAccessRuleProtection($true, $false)
    $rule = [Security.AccessControl.FileSystemAccessRule]::new(
        $identity.User,
        [Security.AccessControl.FileSystemRights]::FullControl,
        [Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit',
        [Security.AccessControl.PropagationFlags]::None,
        [Security.AccessControl.AccessControlType]::Allow
    )
    $security.AddAccessRule($rule)
    [IO.Directory]::SetAccessControl($path, $security)
    return $path
}

function Invoke-WithSwitcherLock {
    param([Parameter(Mandatory = $true)][scriptblock]$Action)
    $mutex = New-Object Threading.Mutex($false, $script:SwitcherMutexName)
    $acquired = $false
    try {
        try {
            $acquired = $mutex.WaitOne(0)
        }
        catch [Threading.AbandonedMutexException] {
            $acquired = $true
        }
        if (-not $acquired) {
            throw 'Another Codex App switch operation is already running for this Windows session.'
        }
        return (& $Action)
    }
    finally {
        if ($acquired) {
            $mutex.ReleaseMutex()
        }
        $mutex.Dispose()
    }
}

function Read-Utf8Text {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return ''
    }
    return [IO.File]::ReadAllText($Path)
}

function Write-Utf8TextAtomic {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Text
    )
    $directory = Split-Path -Parent $Path
    New-DirectoryIfMissing -Path $directory
    $temporary = Join-Path $directory ('.codex-switcher-{0}.tmp' -f [Guid]::NewGuid().ToString('N'))
    $encoding = New-Object Text.UTF8Encoding($false)
    try {
        [IO.File]::WriteAllText($temporary, $Text, $encoding)
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    }
    finally {
        if (Test-Path -LiteralPath $temporary) {
            Remove-Item -LiteralPath $temporary -Force
        }
    }
}

function Get-TextSha256 {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Text)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($Text)
        return (($sha.ComputeHash($bytes) | ForEach-Object { $_.ToString('x2') }) -join '')
    }
    finally {
        $sha.Dispose()
    }
}

function ConvertFrom-TomlKeySegment {
    <#
        Returns the key a segment denotes, or $null when the switcher will not
        resolve it. A literal string carries no escapes, so stripping its quotes is
        exact. A basic string containing a backslash would need full escape
        processing to compare against a provider name, so it fails closed instead.
    #>
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Segment)
    if ($Segment.StartsWith("'")) {
        return $Segment.Substring(1, $Segment.Length - 2)
    }
    if ($Segment.StartsWith('"')) {
        $inner = $Segment.Substring(1, $Segment.Length - 2)
        if ($inner.Contains('\')) {
            return $null
        }
        return $inner
    }
    return $Segment
}

function Get-TomlTableHeader {
    <#
        Describes a table-header line, or returns $null when the line is not one.
        `Resolvable` is false when any segment fails closed, which callers must
        treat as "this document may define the managed provider under a spelling
        the switcher cannot see".
    #>
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Line)
    $isArrayOfTables = $false
    $path = $null
    if ($Line -match $script:TomlArrayTableHeaderPattern) {
        $isArrayOfTables = $true
        $path = $Matches[1]
    }
    elseif ($Line -match $script:TomlTableHeaderPattern) {
        $path = $Matches[1]
    }
    else {
        return $null
    }

    $segments = [Collections.Generic.List[string]]::new()
    $resolvable = $true
    foreach ($match in ([regex]$script:TomlKeySegmentPattern).Matches($path)) {
        $segment = ConvertFrom-TomlKeySegment -Segment $match.Value
        if ($null -eq $segment) {
            $resolvable = $false
            break
        }
        $segments.Add($segment)
    }

    return [pscustomobject]@{
        IsArrayOfTables = $isArrayOfTables
        Resolvable = $resolvable
        Segments = [string[]]$segments.ToArray()
        Path = $path
    }
}

function Test-TomlTableHeader {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Line)
    return ($null -ne (Get-TomlTableHeader -Line $Line))
}

function Test-ManagedProviderHeader {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Line)
    $header = Get-TomlTableHeader -Line $Line
    if ($null -eq $header -or $header.IsArrayOfTables -or -not $header.Resolvable) {
        return $false
    }
    return (
        $header.Segments.Count -eq 2 -and
        $header.Segments[0] -eq 'model_providers' -and
        $header.Segments[1] -eq $script:ManagedProviderId
    )
}

function Test-ManagedProviderAuthHeader {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Line)
    $header = Get-TomlTableHeader -Line $Line
    if ($null -eq $header -or $header.IsArrayOfTables -or -not $header.Resolvable) {
        return $false
    }
    return (
        $header.Segments.Count -eq 3 -and
        $header.Segments[0] -eq 'model_providers' -and
        $header.Segments[1] -eq $script:ManagedProviderId -and
        $header.Segments[2] -eq 'auth'
    )
}

function Get-CodexAppInfo {
    Assert-Windows

    $package = Get-AppxPackage -Name $script:CodexPackageName -ErrorAction SilentlyContinue |
        Sort-Object -Property @{ Expression = {
            $parsed = $null
            if ([Version]::TryParse([string]$_.Version, [ref]$parsed)) { $parsed } else { [Version]::new(0, 0) }
        } } -Descending |
        Select-Object -First 1

    if ($null -ne $package) {
        $executable = Join-Path $package.InstallLocation 'app\ChatGPT.exe'
        return [pscustomobject]@{
            Installed = (Test-Path -LiteralPath $executable)
            Version = [string]$package.Version
            PackageName = $script:CodexPackageName
            InstallLocation = [string]$package.InstallLocation
            ExecutablePath = $executable
            Discovery = 'AppX'
        }
    }

    $codexCommand = Get-Command codex.exe -ErrorAction SilentlyContinue
    if ($null -ne $codexCommand -and $codexCommand.Path -match '^(.*\\OpenAI\.Codex_[^\\]+)\\app\\resources\\codex\.exe$') {
        $installLocation = $Matches[1]
        $executable = Join-Path $installLocation 'app\ChatGPT.exe'
        $version = ''
        if ((Split-Path -Leaf $installLocation) -match '^OpenAI\.Codex_([^_]+)_') {
            $version = $Matches[1]
        }
        return [pscustomobject]@{
            Installed = (Test-Path -LiteralPath $executable)
            Version = $version
            PackageName = $script:CodexPackageName
            InstallLocation = $installLocation
            ExecutablePath = $executable
            Discovery = 'ExecutionAlias'
        }
    }

    return [pscustomobject]@{
        Installed = $false
        Version = ''
        PackageName = $script:CodexPackageName
        InstallLocation = ''
        ExecutablePath = ''
        Discovery = 'NotFound'
    }
}

function Install-CodexApp {
    Assert-Windows
    $existing = Get-CodexAppInfo
    if ($existing.Installed) {
        return $existing
    }

    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if ($null -eq $winget) {
        throw 'Codex App is not installed and winget.exe is unavailable. Install App Installer from Microsoft Store, then retry.'
    }

    $arguments = @(
        'install', '--id', $script:CodexStoreId,
        '--source', 'msstore',
        '--accept-package-agreements',
        '--accept-source-agreements'
    )
    $process = Start-Process -FilePath $winget.Path -ArgumentList $arguments -Wait -PassThru
    if ($process.ExitCode -ne 0) {
        throw "winget failed to install Codex App (exit code $($process.ExitCode))."
    }

    $installed = Get-CodexAppInfo
    if (-not $installed.Installed) {
        throw 'winget completed, but the OpenAI.Codex package could not be discovered.'
    }
    return $installed
}

function Get-CodexAppServerProcesses {
    <#
        The App's work is done by `codex.exe app-server`, which lives under
        %LOCALAPPDATA%\OpenAI\Codex\bin rather than inside the package and is
        therefore invisible to a search of the package directory. It is the
        process that reads config.toml, so "has the App closed" cannot be
        answered without it.

        Measured 2026-08-29: it runs as a child of ChatGPT.exe and, on that
        build, exited before its parent. Parentage is deliberately not the test,
        because the case worth catching is the one where the parent has gone
        first and this has not.

        An interactive `codex` CLI session is not matched: the `app-server`
        subcommand is the App's, and refusing to switch because someone has a
        CLI open would be a false alarm.
    #>
    if (@(Get-Process -Name codex -ErrorAction SilentlyContinue).Count -eq 0) {
        return @()
    }
    $servers = @(Get-CimInstance Win32_Process -Filter "Name='codex.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match '(^|\s)app-server(\s|$)' })
    return @($servers | ForEach-Object { Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue })
}

function Get-CodexAppProcesses {
    $app = Get-CodexAppInfo
    if (-not $app.Installed) {
        return @()
    }
    $installRoot = $app.InstallLocation.TrimEnd('\') + '\'
    $processes = @(Get-Process -Name ChatGPT -ErrorAction SilentlyContinue)
    $matching = [Collections.Generic.List[object]]::new()
    foreach ($process in $processes) {
        try {
            $path = [string]$process.Path
            if ([string]::IsNullOrWhiteSpace($path)) {
                throw "The executable path for ChatGPT process $($process.Id) is unavailable."
            }
            if ($path.StartsWith($installRoot, [StringComparison]::OrdinalIgnoreCase)) {
                $matching.Add($process)
            }
        }
        catch {
            throw "Cannot determine whether ChatGPT process $($process.Id) belongs to Codex App. Close it manually before switching. $($_.Exception.Message)"
        }
    }
    foreach ($server in (Get-CodexAppServerProcesses)) {
        $matching.Add($server)
    }
    return @($matching)
}

function Stop-CodexAppGracefully {
    <#
        Measured against OpenAI.Codex 26.825.4187.0 on 2026-08-29, in both states
        the App can be in, and it does not close in either.

        Started with no profile it showed no visible window at all, so
        `MainWindowHandle` -- which reports only a visible unowned window -- was 0
        for every process and there was nothing to ask. Started with the real
        profile it did show a window and `MainWindowHandle` was set, so
        `CloseMainWindow` reached it; forty seconds later all nine processes and
        the app-server were still running. `WM_CLOSE` posted directly to those
        windows did nothing either. This App exits from its tray menu.

        Asking is still attempted, because a future build may honour it. What
        changed is that the operator is told which of the two situations they are
        in, and in the second is not made to wait out a timeout first.
    #>
    param([ValidateRange(5, 120)][int]$TimeoutSeconds = 30)

    $processes = @(Get-CodexAppProcesses)
    if ($processes.Count -eq 0) {
        return
    }

    $asked = 0
    foreach ($process in $processes) {
        try {
            # Refresh first: MainWindowHandle is cached from when the object was
            # created, which for a just-started App is before its window exists.
            $process.Refresh()
            if ($process.MainWindowHandle -ne 0) {
                [void]$process.CloseMainWindow()
                $asked++
            }
        }
        catch {
            # A protected helper process may not expose a window. The main process
            # is still asked to close, and all helpers are checked below.
        }
    }

    if ($asked -eq 0) {
        $servers = @(Get-CodexAppServerProcesses).Count
        if ($servers -gt 0 -and $servers -eq $processes.Count) {
            # No App windows left, only the server. Pointing at a tray icon that
            # is already gone would be the one instruction that cannot work.
            throw "Codex App's windows have closed but its app-server is still running ($servers process(es) of codex.exe). It holds config.toml, so the switcher waits for it rather than editing underneath it. Give it a moment and retry; if it persists, end codex.exe yourself. The switcher never force-terminates it."
        }
        throw "Codex App is running as $($processes.Count) process(es) and none of them exposes a window to close, which is what this build looks like when it is sitting in the notification area. Quit it from its tray icon -- closing its window is not enough -- then retry. The switcher never force-terminates it."
    }

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        if (@(Get-CodexAppProcesses).Count -eq 0) {
            return
        }
        Start-Sleep -Milliseconds 500
    }

    throw 'Codex App is still running after being asked to close. Finish or cancel active work, quit it from its tray icon, and retry. The switcher never force-terminates it.'
}

function ConvertFrom-SecureStringPlainText {
    param([Parameter(Mandatory = $true)][Security.SecureString]$SecureString)
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureString)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

function ConvertTo-TomlEscapedString {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Value)
    return $Value.Replace('\', '\\').Replace('"', '\"')
}

function Split-TomlLines {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Text)
    # Split on every line ending rather than on one guessed separator: a mixed-ending
    # file would otherwise leave a stray CR or LF inside a line, and the anchored key
    # patterns would then miss a key that is really there and insert a duplicate.
    $newline = if ($Text.Contains("`r`n")) { "`r`n" } else { "`n" }
    $hasTrailingNewline = ($Text -match "(`r`n|`n|`r)$")
    # Assigned directly rather than out of an if-expression: an empty array leaving
    # a statement block is enumerated away and arrives as $null.
    $lines = [string[]]@()
    if ($Text.Length -gt 0) {
        $lines = [string[]][regex]::Split($Text, "`r`n|`n|`r")
    }
    if ($hasTrailingNewline -and $lines.Count -gt 0 -and $lines[$lines.Count - 1] -eq '') {
        $lines = [string[]]$lines[0..($lines.Count - 2)]
    }
    return [pscustomobject]@{
        Lines = [Collections.Generic.List[string]]::new([string[]]$lines)
        Newline = $newline
        HasTrailingNewline = $hasTrailingNewline
    }
}

function Join-TomlLines {
    param(
        [Parameter(Mandatory = $true)][AllowEmptyString()][AllowEmptyCollection()][Collections.Generic.List[string]]$Lines,
        [Parameter(Mandatory = $true)][string]$Newline,
        [bool]$TrailingNewline = $true
    )
    $text = [string]::Join($Newline, $Lines.ToArray())
    if ($TrailingNewline -and -not $text.EndsWith($Newline)) {
        $text += $Newline
    }
    return $text
}

function Assert-SafeTomlForManagedEdit {
    <#
        Fails closed only on forms that could hide the managed selection from a
        line-oriented edit. Quoting elsewhere in the document is the App's own
        output and is left alone -- see docs/runbooks/windows-codex-app-switcher.md
        section 4.1 for the accepted and refused shapes.
    #>
    param([Parameter(Mandatory = $true)][AllowEmptyString()][AllowEmptyCollection()][Collections.Generic.List[string]]$Lines)
    $managedProviderPattern = [regex]::Escape($script:ManagedProviderId)
    $inTopLevel = $true
    $inManagedTable = $false
    $currentPath = ''

    for ($i = 0; $i -lt $Lines.Count; $i++) {
        $line = $Lines[$i]
        $number = $i + 1

        if ($line.Contains('"""') -or $line.Contains("'''")) {
            throw "config.toml line $number uses a multiline string. The switcher cannot safely preserve this TOML form."
        }

        $header = Get-TomlTableHeader -Line $line
        if ($null -ne $header) {
            if (-not $header.Resolvable) {
                throw "config.toml line $number uses an escaped table-key segment the switcher will not resolve. Normalize it to a bare or literal key before using the switcher."
            }
            $segments = $header.Segments
            if ($segments.Count -gt 0 -and $segments[0] -eq 'model_providers') {
                if ($header.IsArrayOfTables) {
                    throw "config.toml line $number declares model_providers as an array of tables. The switcher fails closed rather than edit a TOML document it cannot preserve safely."
                }
                if ($segments.Count -gt 2 -and $segments[1] -eq $script:ManagedProviderId) {
                    throw "config.toml line $number defines a nested table under the managed provider. Remove or migrate that table before using the switcher."
                }
            }
            $inTopLevel = $false
            $inManagedTable = (Test-ManagedProviderHeader -Line $line)
            $currentPath = ($segments -join '.')
            continue
        }

        # An array value left open at end of line makes its continuation lines
        # indistinguishable from table headers, and a header is what decides where
        # the top-level section ends.
        if (($inTopLevel -or $inManagedTable) -and $line -match '=\s*\[[^\]]*$') {
            throw "config.toml line $number opens a multi-line array. Put the array on one line before using the switcher."
        }

        # A quoted key can only shadow the switcher's own keys where those keys
        # live: the top-level section, and the managed provider's own table.
        if (($inTopLevel -or $inManagedTable) -and $line -match $script:TomlQuotedKeyPattern) {
            $where = if ($inTopLevel) { 'the top-level section' } else { "[model_providers.$($script:ManagedProviderId)]" }
            throw "config.toml line $number uses a quoted key in $where. Normalize quoted keys there before using the switcher."
        }

        if ($inTopLevel -and (
                $line -match '^\s*model_providers\s*=' -or
                $line -match ("^\s*model_providers\.$managedProviderPattern(?:\.|\s*=)")
            )) {
            throw "config.toml line $number defines model providers through an inline or dotted key the switcher cannot own safely. Normalize it to provider tables first."
        }

        if ($currentPath -eq 'model_providers' -and $line -match ("^\s*$managedProviderPattern(?:\.|\s*=)")) {
            throw "config.toml line $number defines the managed provider through an inline or dotted key. Normalize it to a [model_providers.$($script:ManagedProviderId)] table first."
        }
    }
}

function Find-TopLevelKeyIndices {
    param(
        [Parameter(Mandatory = $true)][AllowEmptyString()][AllowEmptyCollection()][Collections.Generic.List[string]]$Lines,
        [Parameter(Mandatory = $true)][ValidateSet('model', 'model_provider')][string]$Key
    )
    $indices = [Collections.Generic.List[int]]::new()
    for ($i = 0; $i -lt $Lines.Count; $i++) {
        if (Test-TomlTableHeader -Line $Lines[$i]) {
            break
        }
        if ($Lines[$i] -match ('^\s*{0}\s*=' -f [regex]::Escape($Key))) {
            $indices.Add($i)
        }
    }
    if ($indices.Count -gt 1) {
        throw "config.toml contains more than one top-level '$Key' key. Resolve the duplicate before using the switcher."
    }
    # The unary comma keeps the list a list. Returned bare, a one-element list
    # arrives at the caller as a scalar and an empty one as $null, and every
    # caller here reads .Count under Set-StrictMode.
    return ,$indices
}

function Find-ManagedProviderTableRange {
    <#
        Returns the managed provider table's header index and the exclusive index
        of the next table header, or $null when the table is absent.
    #>
    param([Parameter(Mandatory = $true)][AllowEmptyString()][AllowEmptyCollection()][Collections.Generic.List[string]]$Lines)
    $start = -1
    $duplicate = $false
    for ($i = 0; $i -lt $Lines.Count; $i++) {
        if (Test-ManagedProviderHeader -Line $Lines[$i]) {
            if ($start -eq -1) {
                $start = $i
            }
            else {
                $duplicate = $true
            }
        }
    }
    if ($start -eq -1) {
        return $null
    }
    $end = $Lines.Count
    for ($i = $start + 1; $i -lt $Lines.Count; $i++) {
        if (Test-TomlTableHeader -Line $Lines[$i]) {
            $end = $i
            break
        }
    }
    return [pscustomobject]@{ Start = $start; End = $end; Duplicate = $duplicate }
}

function Set-TopLevelTomlKey {
    param(
        [Parameter(Mandatory = $true)][AllowEmptyString()][AllowEmptyCollection()][Collections.Generic.List[string]]$Lines,
        [Parameter(Mandatory = $true)][ValidateSet('model', 'model_provider')][string]$Key,
        [Parameter(Mandatory = $true)][string]$Line
    )
    $indices = Find-TopLevelKeyIndices -Lines $Lines -Key $Key
    if ($indices.Count -eq 1) {
        $Lines[$indices[0]] = $Line
        return
    }
    $insertAt = 0
    while ($insertAt -lt $Lines.Count -and ($Lines[$insertAt] -match '^\s*(#.*)?$')) {
        $insertAt++
    }
    $Lines.Insert($insertAt, $Line)
}

function Restore-TopLevelTomlKey {
    param(
        [Parameter(Mandatory = $true)][AllowEmptyString()][AllowEmptyCollection()][Collections.Generic.List[string]]$Lines,
        [Parameter(Mandatory = $true)][ValidateSet('model', 'model_provider')][string]$Key,
        [Parameter(Mandatory = $true)]$Original
    )
    $indices = Find-TopLevelKeyIndices -Lines $Lines -Key $Key
    if ([bool]$Original.Present) {
        if ($indices.Count -eq 1) {
            $Lines[$indices[0]] = [string]$Original.Line
        }
        else {
            Set-TopLevelTomlKey -Lines $Lines -Key $Key -Line ([string]$Original.Line)
        }
    }
    elseif ($indices.Count -eq 1) {
        $Lines.RemoveAt($indices[0])
    }
}

function Get-OriginalTopLevelKey {
    param(
        [Parameter(Mandatory = $true)][AllowEmptyString()][AllowEmptyCollection()][Collections.Generic.List[string]]$Lines,
        [Parameter(Mandatory = $true)][ValidateSet('model', 'model_provider')][string]$Key
    )
    $indices = Find-TopLevelKeyIndices -Lines $Lines -Key $Key
    if ($indices.Count -eq 1) {
        return [pscustomobject]@{ Present = $true; Line = $Lines[$indices[0]] }
    }
    return [pscustomobject]@{ Present = $false; Line = '' }
}

function Get-TopLevelTomlValue {
    param(
        [Parameter(Mandatory = $true)][AllowEmptyString()][AllowEmptyCollection()][Collections.Generic.List[string]]$Lines,
        [Parameter(Mandatory = $true)][ValidateSet('model', 'model_provider')][string]$Key
    )
    $indices = Find-TopLevelKeyIndices -Lines $Lines -Key $Key
    if ($indices.Count -eq 1 -and $Lines[$indices[0]] -match ('^\s*{0}\s*=\s*["'']([^"'']+)["'']\s*(?:#.*)?$' -f [regex]::Escape($Key))) {
        return $Matches[1]
    }
    return ''
}

function Set-RcslProviderTable {
    param(
        [Parameter(Mandatory = $true)][AllowEmptyString()][AllowEmptyCollection()][Collections.Generic.List[string]]$Lines,
        [Parameter(Mandatory = $true)][string]$BaseUrl,
        [switch]$AllowExistingManaged
    )

    foreach ($line in $Lines) {
        if (Test-ManagedProviderAuthHeader -Line $line) {
            throw "config.toml already contains [model_providers.$($script:ManagedProviderId).auth]. Remove or migrate that table before using the env_key-based switcher."
        }
    }

    $range = Find-ManagedProviderTableRange -Lines $Lines
    if ($null -ne $range -and $range.Duplicate) {
        throw "config.toml contains more than one [model_providers.$($script:ManagedProviderId)] table."
    }
    if ($null -ne $range -and -not $AllowExistingManaged) {
        throw "config.toml already contains [model_providers.$($script:ManagedProviderId)] without active switcher state. Refusing to overwrite a provider the switcher cannot prove it owns."
    }

    $desired = [ordered]@{
        name = 'name = "RCSL AI Nexus"'
        base_url = ('base_url = "{0}/v1"' -f (ConvertTo-TomlEscapedString -Value $BaseUrl.TrimEnd('/')))
        env_key = 'env_key = "RCSL_API_KEY"'
        wire_api = 'wire_api = "responses"'
    }

    if ($null -eq $range) {
        if ($Lines.Count -gt 0 -and $Lines[$Lines.Count - 1] -ne '') {
            $Lines.Add('')
        }
        $Lines.Add("[model_providers.$($script:ManagedProviderId)]")
        foreach ($line in $desired.Values) {
            $Lines.Add($line)
        }
        return
    }

    $start = $range.Start
    $end = $range.End

    for ($i = $start + 1; $i -lt $end; $i++) {
        if ($Lines[$i] -match '^\s*experimental_bearer_token\s*=') {
            throw "[model_providers.$($script:ManagedProviderId)] already defines 'experimental_bearer_token', which cannot be combined with env_key. Remove or migrate it before using the switcher."
        }
        if ($Lines[$i] -match '^\s*requires_openai_auth\s*=\s*true\s*(?:#.*)?$') {
            throw "[model_providers.$($script:ManagedProviderId)] requires OpenAI authentication and cannot be used with the switcher's env_key authentication."
        }
    }

    foreach ($key in $desired.Keys) {
        # Never name this $matches: -match rebinds the automatic $Matches to a
        # Hashtable on its first success, and the accumulator is lost with it.
        $keyIndices = [Collections.Generic.List[int]]::new()
        for ($i = $start + 1; $i -lt $end; $i++) {
            if ($Lines[$i] -match ('^\s*{0}\s*=' -f [regex]::Escape($key))) {
                $keyIndices.Add($i)
            }
        }
        if ($keyIndices.Count -gt 1) {
            throw "[model_providers.$($script:ManagedProviderId)] contains more than one '$key' key."
        }
        if ($keyIndices.Count -eq 1) {
            $Lines[$keyIndices[0]] = $desired[$key]
        }
        else {
            $Lines.Insert($end, $desired[$key])
            $end++
        }
    }
}

function Get-ManagedProjectionSha256 {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][AllowEmptyCollection()][Collections.Generic.List[string]]$Lines)
    $projection = [Collections.Generic.List[string]]::new()
    foreach ($key in @('model', 'model_provider')) {
        $indices = Find-TopLevelKeyIndices -Lines $Lines -Key $key
        if ($indices.Count -eq 1) {
            $projection.Add($Lines[$indices[0]].Trim())
        }
    }
    $range = Find-ManagedProviderTableRange -Lines $Lines
    if ($null -ne $range) {
        # Blank lines are excluded so that a table appended after ours, which moves
        # the trailing blank inside our range, does not read as the App having
        # changed the selection.
        for ($i = $range.Start; $i -lt $range.End; $i++) {
            $trimmed = $Lines[$i].Trim()
            if ($trimmed -ne '') {
                $projection.Add($trimmed)
            }
        }
    }
    return (Get-TextSha256 -Text ([string]::Join("`n", $projection.ToArray())))
}

function Get-ManagedProviderIssues {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][AllowEmptyCollection()][Collections.Generic.List[string]]$Lines)
    $issues = [Collections.Generic.List[string]]::new()
    $range = Find-ManagedProviderTableRange -Lines $Lines
    if ($null -eq $range) {
        return ,$issues
    }
    if ($range.Duplicate) {
        $issues.Add("Duplicate [model_providers.$($script:ManagedProviderId)] tables were found.")
    }
    $start = $range.Start
    $end = $range.End

    $expectedStrings = [ordered]@{
        name = 'RCSL AI Nexus'
        env_key = 'RCSL_API_KEY'
        wire_api = 'responses'
    }
    foreach ($key in $expectedStrings.Keys) {
        $values = @()
        for ($i = $start + 1; $i -lt $end; $i++) {
            if ($Lines[$i] -match ('^\s*{0}\s*=\s*["'']([^"'']*)["'']\s*(?:#.*)?$' -f [regex]::Escape($key))) {
                $values += $Matches[1]
            }
        }
        if ($values.Count -ne 1 -or $values[0] -ne $expectedStrings[$key]) {
            $issues.Add("Provider key '$key' must appear exactly once with value '$($expectedStrings[$key])'.")
        }
    }

    $baseUrls = @()
    for ($i = $start + 1; $i -lt $end; $i++) {
        if ($Lines[$i] -match '^\s*base_url\s*=\s*["'']([^"'']+)["'']\s*(?:#.*)?$') {
            $baseUrls += $Matches[1]
        }
        if ($Lines[$i] -match '^\s*experimental_bearer_token\s*=' -or $Lines[$i] -match '^\s*requires_openai_auth\s*=\s*true\s*(?:#.*)?$') {
            $issues.Add('Provider authentication conflicts with env_key-based Nexus authentication.')
        }
    }
    $baseUri = $null
    if ($baseUrls.Count -ne 1 -or -not [Uri]::TryCreate($baseUrls[0], [UriKind]::Absolute, [ref]$baseUri) -or $baseUri.Scheme -ne 'https' -or -not $baseUrls[0].TrimEnd('/').EndsWith('/v1')) {
        $issues.Add("Provider key 'base_url' must appear exactly once as an absolute HTTPS URL ending in /v1.")
    }
    return ,$issues
}

function Assert-DocumentCanBeSwitched {
    <#
        Rehearses the whole edit against a copy and throws the copy away.

        `Assert-SafeTomlForManagedEdit` is not the only thing that refuses on the
        document alone: a duplicated top-level key, a second managed table, a
        duplicated key inside it, `experimental_bearer_token` and
        `requires_openai_auth = true` are all decided by reading, and all of them
        used to surface from the write, which happens after the operator's App has
        been closed for them. Running the transformation twice is cheap; closing
        somebody's App to tell them about a duplicate line is not.
    #>
    param(
        [Parameter(Mandatory = $true)][AllowEmptyString()][AllowEmptyCollection()][Collections.Generic.List[string]]$Lines,
        [Parameter(Mandatory = $true)][string]$BaseUrl,
        [Parameter(Mandatory = $true)][string]$Capability,
        [switch]$AllowExistingManaged
    )
    Assert-SafeTomlForManagedEdit -Lines $Lines
    $rehearsal = [Collections.Generic.List[string]]::new($Lines)
    Set-TopLevelTomlKey -Lines $rehearsal -Key 'model_provider' -Line ('model_provider = "{0}"' -f $script:ManagedProviderId)
    Set-TopLevelTomlKey -Lines $rehearsal -Key 'model' -Line ('model = "{0}"' -f (ConvertTo-TomlEscapedString -Value $Capability))
    Set-RcslProviderTable -Lines $rehearsal -BaseUrl $BaseUrl -AllowExistingManaged:$AllowExistingManaged
}

function Assert-DocumentCanBeRestored {
    <#
        The same rehearsal for the way back. Restoration reads the document too,
        and a refusal there would cost the operator a closed App for nothing.
    #>
    param(
        [Parameter(Mandatory = $true)][AllowEmptyString()][AllowEmptyCollection()][Collections.Generic.List[string]]$Lines,
        $State
    )
    Assert-SafeTomlForManagedEdit -Lines $Lines
    $rehearsal = [Collections.Generic.List[string]]::new($Lines)
    if ($null -eq $State) {
        [void](Get-TopLevelTomlValue -Lines $rehearsal -Key 'model_provider')
        return
    }
    if (Test-StateOwnsManagedProvider -State $State) {
        if (Test-ShouldRefreshManagedProvider -Lines $rehearsal -State $State) {
            Set-RcslProviderTable -Lines $rehearsal -BaseUrl (Get-NormalizedGatewayBaseUrl -BaseUrl ([string]$State.GatewayBaseUrl)) -AllowExistingManaged
        }
        Restore-TopLevelTomlKey -Lines $rehearsal -Key 'model' -Original $State.OriginalModel
        Restore-TopLevelTomlKey -Lines $rehearsal -Key 'model_provider' -Original $State.OriginalModelProvider
        return
    }
    [void](Get-TopLevelTomlValue -Lines $rehearsal -Key 'model_provider')
}

function Test-StateOwnsManagedProvider {
    param($State)
    return (
        $null -ne $State -and
        $null -ne $State.PSObject.Properties['ProviderId'] -and
        [string]$State.ProviderId -eq $script:ManagedProviderId
    )
}

function Test-ShouldRefreshManagedProvider {
    <#
        Refresh a table that is there; never put one back that is not.

        Re-adding it would resurrect a definition the operator had deleted, while
        the GUI reported it as preserved, and would make every no-op restore
        rewrite config.toml without a backup. One helper rather than the same
        condition in two places, so the rehearsal and the write cannot drift.
    #>
    param(
        [Parameter(Mandatory = $true)][AllowEmptyString()][AllowEmptyCollection()][Collections.Generic.List[string]]$Lines,
        $State
    )
    if (-not (Test-StateOwnsManagedProvider -State $State)) {
        return $false
    }
    return ($null -ne (Find-ManagedProviderTableRange -Lines $Lines))
}

function New-ConfigBackup {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Text)
    $stateDirectory = Protect-SwitcherStateDirectory
    $backupDirectory = Join-Path $stateDirectory 'backups'
    New-DirectoryIfMissing -Path $backupDirectory
    $stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')
    $backupPath = Join-Path $backupDirectory ("config.toml.before-rcsl-$stamp")
    Write-Utf8TextAtomic -Path $backupPath -Text $Text
    return $backupPath
}

function Save-SwitcherState {
    param([Parameter(Mandatory = $true)]$State)
    [void](Protect-SwitcherStateDirectory)
    $path = Get-SwitcherStatePath
    New-DirectoryIfMissing -Path (Split-Path -Parent $path)
    $json = $State | ConvertTo-Json -Depth 8
    Write-Utf8TextAtomic -Path $path -Text ($json + "`n")
}

function Get-SwitcherState {
    $path = Get-SwitcherStatePath
    if (-not (Test-Path -LiteralPath $path)) {
        return $null
    }
    # Read-Utf8Text rather than Get-Content -Raw. The state is written as UTF-8
    # without a BOM, and Get-Content decodes a BOM-less file in the system
    # codepage: a ConfigPath or BackupPath containing any non-ASCII character
    # comes back mangled, and restoration then refuses on a path mismatch the
    # operator cannot resolve.
    $json = Read-Utf8Text -Path $path
    if ([string]::IsNullOrWhiteSpace($json)) {
        throw "Switcher recovery state at '$path' is empty. Preserve it and recover manually; the switcher will not treat an empty state as no state."
    }
    return ($json | ConvertFrom-Json)
}

function Assert-SwitcherStateUsable {
    param(
        $State,
        [Parameter(Mandatory = $true)][string]$ConfigPath
    )
    if ($null -eq $State) {
        return
    }
    $schemaProperty = $State.PSObject.Properties['SchemaVersion']
    if ($null -eq $schemaProperty -or [int]$schemaProperty.Value -ne $script:StateSchemaVersion) {
        throw 'Switcher recovery state is missing a supported schema version. Preserve it and recover manually; the switcher will not overwrite unknown state.'
    }
    if ([string]$State.Mode -in @('preparing-rcsl', 'rcsl') -and [string]$State.ConfigPath -ne $ConfigPath) {
        throw "The switcher has an active RCSL session for '$($State.ConfigPath)', but CODEX_HOME now resolves to '$ConfigPath'. Restore OpenAI with the original CODEX_HOME before switching another profile."
    }
}

function Set-StateProperty {
    param(
        [Parameter(Mandatory = $true)]$State,
        [Parameter(Mandatory = $true)][string]$Name,
        $Value
    )
    $State | Add-Member -MemberType NoteProperty -Name $Name -Value $Value -Force
}

function Get-NormalizedGatewayBaseUrl {
    param([Parameter(Mandatory = $true)][string]$BaseUrl)
    $uri = $null
    $invalid = (
        -not [Uri]::TryCreate($BaseUrl, [UriKind]::Absolute, [ref]$uri) -or
        $uri.Scheme -ne 'https' -or
        -not [string]::IsNullOrEmpty($uri.UserInfo) -or
        -not [string]::IsNullOrEmpty($uri.Query) -or
        -not [string]::IsNullOrEmpty($uri.Fragment) -or
        $uri.AbsolutePath.Trim('/') -ne ''
    )
    if ($invalid) {
        throw 'The gateway base URL must be an HTTPS origin without credentials, a path, a query, or a fragment.'
    }
    return $uri.GetLeftPart([UriPartial]::Authority).TrimEnd('/')
}

function Get-ModelCatalogueIds {
    <#
        Reads the capability names out of a `/v1/models` body.

        Every access goes through PSObject.Properties because dotting into a
        missing property is a terminating error under Set-StrictMode, not $null.
        A proxy, a captive portal or an error page answering 200 with a body that
        has no `data` would otherwise abort the switch with "The property 'data'
        cannot be found on this object", which tells the operator nothing.
    #>
    param($Response)
    $ids = [Collections.Generic.List[string]]::new()
    if ($null -eq $Response) {
        return ,$ids
    }
    $data = $Response.PSObject.Properties['data']
    if ($null -eq $data -or $null -eq $data.Value) {
        return ,$ids
    }
    foreach ($entry in @($data.Value)) {
        if ($null -eq $entry) {
            continue
        }
        $id = $entry.PSObject.Properties['id']
        if ($null -ne $id -and $null -ne $id.Value) {
            $ids.Add([string]$id.Value)
        }
    }
    return ,$ids
}

function Test-RcslGateway {
    param(
        [Parameter(Mandatory = $true)][Security.SecureString]$ApiKey,
        [string]$BaseUrl = $script:DefaultGatewayBaseUrl,
        [string]$Capability = $script:DefaultCapability,
        [ValidateRange(5, 120)][int]$TimeoutSeconds = 30
    )
    $BaseUrl = Get-NormalizedGatewayBaseUrl -BaseUrl $BaseUrl

    $plainKey = ConvertFrom-SecureStringPlainText -SecureString $ApiKey
    try {
        if ([string]::IsNullOrWhiteSpace($plainKey) -or $plainKey -match '\s') {
            throw 'The API key is empty or contains whitespace.'
        }
        $headers = @{ Authorization = "Bearer $plainKey"; Accept = 'application/json' }
        $modelsUri = '{0}/v1/models' -f $BaseUrl.TrimEnd('/')
        $response = Invoke-RestMethod -Method Get -Uri $modelsUri -Headers $headers -TimeoutSec $TimeoutSeconds
        $ids = Get-ModelCatalogueIds -Response $response
        if ($ids -notcontains $Capability) {
            throw "The key reached the gateway, but GET /v1/models did not include capability '$Capability'."
        }
        return [pscustomobject]@{
            Passed = $true
            Endpoint = $modelsUri
            Capability = $Capability
            Models = $ids
        }
    }
    finally {
        $plainKey = $null
        $headers = $null
    }
}

function Start-CodexAppWithEnvironment {
    param(
        [Parameter(Mandatory = $true)][string]$ExecutablePath,
        [Security.SecureString]$ApiKey
    )
    $previousKey = [Environment]::GetEnvironmentVariable('RCSL_API_KEY', 'Process')
    $plainKey = $null
    try {
        if ($null -ne $ApiKey) {
            $plainKey = ConvertFrom-SecureStringPlainText -SecureString $ApiKey
            [Environment]::SetEnvironmentVariable('RCSL_API_KEY', $plainKey, 'Process')
        }
        else {
            [Environment]::SetEnvironmentVariable('RCSL_API_KEY', $null, 'Process')
        }
        return (Start-Process -FilePath $ExecutablePath -PassThru)
    }
    finally {
        [Environment]::SetEnvironmentVariable('RCSL_API_KEY', $previousKey, 'Process')
        $plainKey = $null
    }
}

function Confirm-CodexAppLaunch {
    <#
        A sample, not a guarantee, and callers must not describe it as one. The
        process that reads and rewrites config.toml is `codex.exe app-server`,
        a child that need not have started within the couple of seconds this
        waits, so a rewrite can still follow a passing check. What this does rule
        out is the App failing to start, exiting immediately, or rewriting the
        selection while the switcher is still watching.
    #>
    param(
        [Collections.Generic.List[string]]$ExpectedManagedLines,
        [ValidateRange(5, 60)][int]$TimeoutSeconds = 15
    )
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        if (@(Get-CodexAppProcesses).Count -gt 0) {
            Start-Sleep -Milliseconds 2000
            if (@(Get-CodexAppProcesses).Count -eq 0) {
                throw 'The discovered Codex App process exited during startup.'
            }
            if ($null -ne $ExpectedManagedLines) {
                $currentText = Read-Utf8Text -Path (Get-CodexConfigPath)
                $currentParts = Split-TomlLines -Text $currentText
                Assert-SafeTomlForManagedEdit -Lines $currentParts.Lines
                $expectedHash = Get-ManagedProjectionSha256 -Lines $ExpectedManagedLines
                $actualHash = Get-ManagedProjectionSha256 -Lines $currentParts.Lines
                if ($expectedHash -ne $actualHash) {
                    throw 'Codex App launched but changed the managed provider selection during startup. Use the recovery state to restore OpenAI; this App build has not accepted the switch.'
                }
            }
            return
        }
        Start-Sleep -Milliseconds 250
    }
    throw 'ChatGPT.exe was started, but a process belonging to the discovered Codex App package was not observed before the timeout. Package internals may have changed.'
}

function Invoke-EnableRcslCodexAppCore {
    param(
        [Parameter(Mandatory = $true)][Security.SecureString]$ApiKey,
        [string]$BaseUrl = $script:DefaultGatewayBaseUrl,
        [string]$Capability = $script:DefaultCapability,
        [switch]$InstallIfMissing,
        [switch]$ValidateGateway,
        [ValidateRange(5, 120)][int]$CloseTimeoutSeconds = 30
    )
    Assert-Windows

    $BaseUrl = Get-NormalizedGatewayBaseUrl -BaseUrl $BaseUrl
    if ($Capability -notmatch '^[a-z][a-z0-9_-]*$') {
        throw 'The capability must be a lowercase capability identifier.'
    }

    $app = Get-CodexAppInfo
    if (-not $app.Installed) {
        if (-not $InstallIfMissing) {
            throw 'Codex App is not installed.'
        }
        $app = Install-CodexApp
    }

    $configPath = Get-CodexConfigPath

    # Refuse an unownable document or unusable state before the operator's App is
    # closed, so a refusal costs them nothing. The App rewrites config.toml as it
    # exits, so the authoritative pass below re-reads it after the close.
    $preflight = Split-TomlLines -Text (Read-Utf8Text -Path $configPath)
    $preflightState = Get-SwitcherState
    Assert-SwitcherStateUsable -State $preflightState -ConfigPath $configPath
    $preflightActive = ($null -ne $preflightState -and [string]$preflightState.Mode -in @('preparing-rcsl', 'rcsl'))
    Assert-DocumentCanBeSwitched -Lines $preflight.Lines -BaseUrl $BaseUrl -Capability $Capability `
        -AllowExistingManaged:($preflightActive -or (Test-StateOwnsManagedProvider -State $preflightState))

    if ($ValidateGateway) {
        [void](Test-RcslGateway -ApiKey $ApiKey -BaseUrl $BaseUrl -Capability $Capability)
    }

    Stop-CodexAppGracefully -TimeoutSeconds $CloseTimeoutSeconds

    $originalText = Read-Utf8Text -Path $configPath
    $parts = Split-TomlLines -Text $originalText
    Assert-SafeTomlForManagedEdit -Lines $parts.Lines
    $state = Get-SwitcherState
    Assert-SwitcherStateUsable -State $state -ConfigPath $configPath
    $activeState = ($null -ne $state -and [string]$state.Mode -in @('preparing-rcsl', 'rcsl'))
    $ownedState = ($null -ne $state -and $null -ne $state.PSObject.Properties['ProviderId'] -and [string]$state.ProviderId -eq $script:ManagedProviderId)
    $captureOriginal = -not $activeState
    $originalModel = Get-OriginalTopLevelKey -Lines $parts.Lines -Key 'model'
    $originalModelProvider = Get-OriginalTopLevelKey -Lines $parts.Lines -Key 'model_provider'
    if (-not $activeState -and (Get-TopLevelTomlValue -Lines $parts.Lines -Key 'model_provider') -eq $script:ManagedProviderId) {
        throw 'The managed provider is selected while recovery state says the previous switch is inactive. Use Switch App back to OpenAI first so the recorded original selection is reconciled.'
    }

    Set-TopLevelTomlKey -Lines $parts.Lines -Key 'model_provider' -Line ('model_provider = "{0}"' -f $script:ManagedProviderId)
    Set-TopLevelTomlKey -Lines $parts.Lines -Key 'model' -Line ('model = "{0}"' -f (ConvertTo-TomlEscapedString -Value $Capability))
    Set-RcslProviderTable -Lines $parts.Lines -BaseUrl $BaseUrl -AllowExistingManaged:($activeState -or $ownedState)
    $updatedText = Join-TomlLines -Lines $parts.Lines -Newline $parts.Newline -TrailingNewline $true

    if ($captureOriginal) {
        $backupPath = New-ConfigBackup -Text $originalText
        $state = [pscustomobject]@{
            SchemaVersion = $script:StateSchemaVersion
            Mode = 'preparing-rcsl'
            ConfigPath = $configPath
            BackupPath = $backupPath
            ConfigSha256Before = Get-TextSha256 -Text $originalText
            OriginalModel = $originalModel
            OriginalModelProvider = $originalModelProvider
            ProviderId = $script:ManagedProviderId
            GatewayBaseUrl = $BaseUrl.TrimEnd('/')
            Capability = $Capability
            AppVersion = $app.Version
            SwitchedAtUtc = [DateTime]::UtcNow.ToString('o')
        }
        Save-SwitcherState -State $state
    }
    Write-Utf8TextAtomic -Path $configPath -Text $updatedText

    $state.Mode = 'rcsl'
    $state.GatewayBaseUrl = $BaseUrl.TrimEnd('/')
    $state.Capability = $Capability
    $state.AppVersion = $app.Version
    Set-StateProperty -State $state -Name 'ManagedSha256After' -Value (Get-ManagedProjectionSha256 -Lines $parts.Lines)
    Save-SwitcherState -State $state

    $process = Start-CodexAppWithEnvironment -ExecutablePath $app.ExecutablePath -ApiKey $ApiKey
    Confirm-CodexAppLaunch -ExpectedManagedLines $parts.Lines
    return [pscustomobject]@{
        Mode = 'rcsl-configured'
        AppVersion = $app.Version
        ProcessId = $process.Id
        ConfigPath = $configPath
        BackupPath = $state.BackupPath
        GatewayBaseUrl = $BaseUrl.TrimEnd('/')
        Capability = $Capability
        InteractiveAcceptanceRequired = $true
    }
}

function Invoke-DisableRcslCodexAppCore {
    param(
        [switch]$InstallIfMissing,
        [switch]$RemovePersistedUserKey,
        [ValidateRange(5, 120)][int]$CloseTimeoutSeconds = 30
    )
    Assert-Windows

    $app = Get-CodexAppInfo
    if (-not $app.Installed) {
        if (-not $InstallIfMissing) {
            throw 'Codex App is not installed.'
        }
        $app = Install-CodexApp
    }

    $configPath = Get-CodexConfigPath

    # Same reason as the enable path: a document the switcher will not edit is a
    # refusal, and a refusal must not cost the operator a closed App.
    $preflight = Split-TomlLines -Text (Read-Utf8Text -Path $configPath)
    Assert-DocumentCanBeRestored -Lines $preflight.Lines -State (Get-SwitcherState)

    Stop-CodexAppGracefully -TimeoutSeconds $CloseTimeoutSeconds

    $state = Get-SwitcherState
    $text = Read-Utf8Text -Path $configPath
    $parts = Split-TomlLines -Text $text
    Assert-SafeTomlForManagedEdit -Lines $parts.Lines
    $currentProvider = Get-TopLevelTomlValue -Lines $parts.Lines -Key 'model_provider'
    $configChanged = $false

    if ($null -eq $state) {
        if ($currentProvider -eq $script:ManagedProviderId) {
            throw 'The managed provider is selected but recovery state is missing. The switcher will not guess what OpenAI selection preceded it; follow the manual recovery procedure.'
        }
    }
    else {
        $schemaProperty = $state.PSObject.Properties['SchemaVersion']
        if ($null -eq $schemaProperty -or [int]$schemaProperty.Value -ne $script:StateSchemaVersion) {
            throw 'Switcher recovery state uses an unsupported schema. Preserve it and recover manually; no configuration was changed.'
        }
        if ([string]$state.ConfigPath -ne $configPath) {
            throw "The recovery state belongs to '$($state.ConfigPath)', but CODEX_HOME now resolves to '$configPath'. Restore the original CODEX_HOME value and retry."
        }
        if (Test-ShouldRefreshManagedProvider -Lines $parts.Lines -State $state) {
            $restoredBaseUrl = Get-NormalizedGatewayBaseUrl -BaseUrl ([string]$state.GatewayBaseUrl)
            Set-RcslProviderTable -Lines $parts.Lines -BaseUrl $restoredBaseUrl -AllowExistingManaged
            $configChanged = $true
        }
        $activeState = ([string]$state.Mode -in @('preparing-rcsl', 'rcsl'))
        if ($activeState -or $currentProvider -eq $script:ManagedProviderId) {
            Restore-TopLevelTomlKey -Lines $parts.Lines -Key 'model' -Original $state.OriginalModel
            Restore-TopLevelTomlKey -Lines $parts.Lines -Key 'model_provider' -Original $state.OriginalModelProvider
            $configChanged = $true
        }
        $state.Mode = 'openai'
        Set-StateProperty -State $state -Name 'RestoredAtUtc' -Value ([DateTime]::UtcNow.ToString('o'))
        $state.AppVersion = $app.Version
    }

    if ($configChanged) {
        $updatedText = Join-TomlLines -Lines $parts.Lines -Newline $parts.Newline -TrailingNewline $true
        Write-Utf8TextAtomic -Path $configPath -Text $updatedText
    }
    if ($null -ne $state) {
        Set-StateProperty -State $state -Name 'ManagedSha256AfterRestore' -Value (Get-ManagedProjectionSha256 -Lines $parts.Lines)
        Save-SwitcherState -State $state
    }

    if ($RemovePersistedUserKey) {
        [Environment]::SetEnvironmentVariable('RCSL_API_KEY', $null, 'User')
    }

    $process = Start-CodexAppWithEnvironment -ExecutablePath $app.ExecutablePath
    Confirm-CodexAppLaunch
    return [pscustomobject]@{
        Mode = 'openai'
        AppVersion = $app.Version
        ProcessId = $process.Id
        ConfigPath = $configPath
        ProviderDefinitionPreserved = $true
        PersistedUserKeyRemoved = [bool]$RemovePersistedUserKey
    }
}

function Enable-RcslCodexApp {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][Security.SecureString]$ApiKey,
        [string]$BaseUrl = $script:DefaultGatewayBaseUrl,
        [string]$Capability = $script:DefaultCapability,
        [switch]$InstallIfMissing,
        [switch]$ValidateGateway,
        [ValidateRange(5, 120)][int]$CloseTimeoutSeconds = 30
    )
    $parameters = @{} + $PSBoundParameters
    return (Invoke-WithSwitcherLock -Action { Invoke-EnableRcslCodexAppCore @parameters })
}

function Disable-RcslCodexApp {
    [CmdletBinding()]
    param(
        [switch]$InstallIfMissing,
        [switch]$RemovePersistedUserKey,
        [ValidateRange(5, 120)][int]$CloseTimeoutSeconds = 30
    )
    $parameters = @{} + $PSBoundParameters
    return (Invoke-WithSwitcherLock -Action { Invoke-DisableRcslCodexAppCore @parameters })
}

function Get-ProjectConfigPaths {
    param([string]$ProjectPath = (Get-Location).Path)
    $paths = [Collections.Generic.List[string]]::new()
    if ([string]::IsNullOrWhiteSpace($ProjectPath) -or -not (Test-Path -LiteralPath $ProjectPath -PathType Container)) {
        return ,$paths
    }
    $directory = [IO.DirectoryInfo](Resolve-Path -LiteralPath $ProjectPath).Path
    $userConfigPath = [IO.Path]::GetFullPath((Get-CodexConfigPath))
    while ($null -ne $directory) {
        $candidate = Join-Path $directory.FullName '.codex\config.toml'
        if ((Test-Path -LiteralPath $candidate -PathType Leaf) -and [IO.Path]::GetFullPath($candidate) -ne $userConfigPath) {
            $projectText = Read-Utf8Text -Path $candidate
            $projectParts = Split-TomlLines -Text $projectText
            if ((Find-TopLevelKeyIndices -Lines $projectParts.Lines -Key 'model').Count -gt 0) {
                $paths.Add($candidate)
            }
        }
        $directory = $directory.Parent
    }
    return ,$paths
}

function Get-CodexSwitcherStatus {
    param([string]$ProjectPath = (Get-Location).Path)
    Assert-Windows
    $app = Get-CodexAppInfo
    $configPath = Get-CodexConfigPath
    $text = Read-Utf8Text -Path $configPath
    $parts = Split-TomlLines -Text $text
    $issues = [Collections.Generic.List[string]]::new()
    try {
        Assert-SafeTomlForManagedEdit -Lines $parts.Lines
    }
    catch {
        $issues.Add($_.Exception.Message)
    }

    $model = ''
    $provider = ''
    try {
        $model = Get-TopLevelTomlValue -Lines $parts.Lines -Key 'model'
        $provider = Get-TopLevelTomlValue -Lines $parts.Lines -Key 'model_provider'
    }
    catch {
        $issues.Add($_.Exception.Message)
    }

    $hasProviderTable = $false
    foreach ($line in $parts.Lines) {
        if (Test-ManagedProviderHeader -Line $line) {
            $hasProviderTable = $true
            break
        }
    }
    if ($provider -eq $script:ManagedProviderId -and -not $hasProviderTable) {
        $issues.Add("model_provider selects $($script:ManagedProviderId), but its provider table is absent.")
    }
    if ($hasProviderTable) {
        # Not @(...): these functions return their list through a unary comma, and a
        # second wrap would make the list itself the single element.
        foreach ($providerIssue in (Get-ManagedProviderIssues -Lines $parts.Lines)) {
            $issues.Add($providerIssue)
        }
    }

    # A read-only status must not fail because one unreadable process cannot be
    # attributed; that refusal belongs to the switch path, which needs certainty.
    $appRunning = $null
    try {
        $appRunning = (@(Get-CodexAppProcesses).Count -gt 0)
    }
    catch {
        $issues.Add($_.Exception.Message)
    }

    $state = Get-SwitcherState
    $managedHashMatchesState = $null
    if ($null -ne $state) {
        $stateMode = [string]$state.Mode
        $stateConfigPath = $state.PSObject.Properties['ConfigPath']
        if ($null -ne $stateConfigPath -and [string]$stateConfigPath.Value -ne $configPath) {
            $issues.Add("Recovery state belongs to '$($stateConfigPath.Value)', not the active config '$configPath'.")
        }
        switch ($stateMode) {
            'rcsl' {
                if ($provider -ne $script:ManagedProviderId) {
                    $issues.Add('Recovery state says RCSL mode, but the managed provider is not selected.')
                }
                $stateCapability = $state.PSObject.Properties['Capability']
                if ($null -eq $stateCapability -or $model -ne [string]$stateCapability.Value) {
                    $issues.Add('The selected model does not match the capability recorded in recovery state.')
                }
                $hashProperty = $state.PSObject.Properties['ManagedSha256After']
                if ($null -eq $hashProperty) {
                    $issues.Add('RCSL recovery state has no managed-projection hash.')
                }
                else {
                    # Guarded for the same reason as the reads above: the
                    # projection walks the top-level keys and throws on a
                    # duplicate, and a read-only status that dies takes eight
                    # other checks down with it without naming the offending line.
                    try {
                        $managedHashMatchesState = ([string]$hashProperty.Value -eq (Get-ManagedProjectionSha256 -Lines $parts.Lines))
                        if (-not $managedHashMatchesState) {
                            $issues.Add('The managed model/provider projection has drifted since the switch was recorded.')
                        }
                    }
                    catch {
                        $issues.Add($_.Exception.Message)
                    }
                }
            }
            'openai' {
                if ($provider -eq $script:ManagedProviderId) {
                    $issues.Add('Recovery state says OpenAI mode, but the managed provider is still selected.')
                }
            }
            'preparing-rcsl' {
                $issues.Add('Recovery state records an interrupted RCSL transition. Recover manually before switching again.')
            }
            default {
                $issues.Add("Recovery state uses unknown mode '$stateMode'.")
            }
        }
    }
    $projectConfigs = [Collections.Generic.List[string]]::new()
    try {
        $projectConfigs = Get-ProjectConfigPaths -ProjectPath $ProjectPath
    }
    catch {
        $issues.Add($_.Exception.Message)
    }
    return [pscustomobject]@{
        IsWindows = ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT)
        AppInstalled = $app.Installed
        AppVersion = $app.Version
        AppRunning = $appRunning
        ConfigPath = $configPath
        ConfigExists = (Test-Path -LiteralPath $configPath)
        Model = $model
        ModelProvider = $provider
        RcslProviderDefined = $hasProviderTable
        ManagedProviderId = $script:ManagedProviderId
        UserSelectionMode = if ($provider -eq $script:ManagedProviderId) { 'rcsl-user-default' } else { 'openai-or-other-user-default' }
        EffectiveMode = if ($provider -eq $script:ManagedProviderId) { 'rcsl-user-default' } else { 'openai-or-other-user-default' }
        ConfigurationIssues = @($issues)
        ManagedHashMatchesState = $managedHashMatchesState
        HigherPrecedenceProjectConfigs = $projectConfigs
        State = $state
        PersistedUserKeyPresent = -not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable('RCSL_API_KEY', 'User'))
        PersistedMachineKeyPresent = -not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable('RCSL_API_KEY', 'Machine'))
    }
}

Export-ModuleMember -Function @(
    'Disable-RcslCodexApp',
    'Enable-RcslCodexApp',
    'Get-CodexAppInfo',
    'Get-CodexAppProcesses',
    'Get-CodexAppServerProcesses',
    'Get-CodexConfigPath',
    'Get-CodexSwitcherStatus',
    'Get-NormalizedGatewayBaseUrl',
    'Get-SwitcherState',
    'Install-CodexApp',
    'Stop-CodexAppGracefully',
    'Test-RcslGateway'
)
