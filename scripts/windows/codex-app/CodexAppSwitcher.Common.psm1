Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:CodexPackageName = 'OpenAI.Codex'
$script:CodexStoreId = '9PLM9XGG6VKS'
$script:DefaultGatewayBaseUrl = 'https://llmapi.rcsl.online'
$script:DefaultCapability = 'code'
$script:ManagedProviderId = 'rcsl_nexus_switcher'
$script:SwitcherMutexName = 'Local\RCSL.AI.Nexus.CodexAppSwitcher'
$script:StateSchemaVersion = 2

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

function Get-CodexAppInfo {
    Assert-Windows

    $package = Get-AppxPackage -Name $script:CodexPackageName -ErrorAction SilentlyContinue |
        Sort-Object Version -Descending |
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
    return @($matching)
}

function Stop-CodexAppGracefully {
    param([ValidateRange(5, 120)][int]$TimeoutSeconds = 30)

    $processes = @(Get-CodexAppProcesses)
    if ($processes.Count -eq 0) {
        return
    }

    foreach ($process in $processes) {
        try {
            if ($process.MainWindowHandle -ne 0) {
                [void]$process.CloseMainWindow()
            }
        }
        catch {
            # A protected helper process may not expose a window. The main process
            # is still asked to close, and all helpers are checked below.
        }
    }

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        if (@(Get-CodexAppProcesses).Count -eq 0) {
            return
        }
        Start-Sleep -Milliseconds 500
    }

    throw 'Codex App is still running. Finish or cancel active work, exit the app from its menu or tray icon, and retry. The switcher never force-terminates it.'
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

function Escape-TomlString {
    param([Parameter(Mandatory = $true)][string]$Value)
    return $Value.Replace('\', '\\').Replace('"', '\"')
}

function Split-TomlLines {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Text)
    $newline = if ($Text.Contains("`r`n")) { "`r`n" } else { "`n" }
    $hasTrailingNewline = $Text.EndsWith($newline)
    $lines = if ($Text.Length -eq 0) { [string[]]@() } else { [string[]]$Text.Split([string[]]@($newline), [StringSplitOptions]::None) }
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
        [Parameter(Mandatory = $true)][Collections.Generic.List[string]]$Lines,
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
    param([Parameter(Mandatory = $true)][Collections.Generic.List[string]]$Lines)
    $managedProviderPattern = [regex]::Escape($script:ManagedProviderId)
    $currentTable = ''
    for ($i = 0; $i -lt $Lines.Count; $i++) {
        $line = $Lines[$i]
        if ($line -match '("""|'''''')') {
            throw "config.toml line $($i + 1) uses a multiline string. The switcher cannot safely preserve this TOML form."
        }
        if ($line -match '^\s*model_providers\.[^=]*["'']') {
            throw "config.toml line $($i + 1) uses a quoted dotted model-provider key. Normalize it to an unquoted provider table before using the switcher."
        }
        if ($line -match '^\s*["''][^"'']+["'']\s*=') {
            throw "config.toml line $($i + 1) uses a quoted key. Normalize quoted keys before using the switcher."
        }
        if ($line -match '^\s*\[\[') {
            throw "config.toml line $($i + 1) uses an array-of-tables header. The switcher fails closed rather than edit a TOML document it cannot preserve safely."
        }
        if ($line -match '^\s*\[[^\]]+\]\s*(?:#.*)?$') {
            $headerName = [regex]::Match($line, '^\s*\[([^\]]+)\]').Groups[1].Value
            if ($headerName -match '["'']') {
                throw "config.toml line $($i + 1) uses a quoted table segment. Normalize it before using the switcher."
            }
            if ($headerName -notmatch '^[A-Za-z0-9_.-]+$') {
                throw "config.toml line $($i + 1) uses an unsupported table-header form. The switcher will not guess at its meaning."
            }
            if ($headerName -match ("^model_providers\.$managedProviderPattern\.")) {
                throw "config.toml line $($i + 1) defines a nested table under the managed provider. Remove or migrate that table before using the switcher."
            }
            $currentTable = $headerName
            continue
        }
        if ($currentTable -eq '' -and ($line -match '^\s*model_providers\s*=' -or $line -match ("^\s*model_providers\.$managedProviderPattern(?:\.|\s*=)"))) {
            throw "config.toml line $($i + 1) defines model providers through an inline or dotted key the switcher cannot own safely. Normalize it to provider tables first."
        }
        if ($currentTable -eq 'model_providers' -and $line -match ("^\s*$managedProviderPattern(?:\.|\s*=)")) {
            throw "config.toml line $($i + 1) defines the managed provider through an inline or dotted key. Normalize it to a [model_providers.$($script:ManagedProviderId)] table first."
        }
    }
}

function Find-TopLevelKeyIndices {
    param(
        [Parameter(Mandatory = $true)][Collections.Generic.List[string]]$Lines,
        [Parameter(Mandatory = $true)][ValidateSet('model', 'model_provider')][string]$Key
    )
    $indices = [Collections.Generic.List[int]]::new()
    for ($i = 0; $i -lt $Lines.Count; $i++) {
        if ($Lines[$i] -match '^\s*\[[A-Za-z0-9_.-]+\]\s*(?:#.*)?$') {
            break
        }
        if ($Lines[$i] -match ('^\s*{0}\s*=' -f [regex]::Escape($Key))) {
            $indices.Add($i)
        }
    }
    if ($indices.Count -gt 1) {
        throw "config.toml contains more than one top-level '$Key' key. Resolve the duplicate before using the switcher."
    }
    return $indices
}

function Set-TopLevelTomlKey {
    param(
        [Parameter(Mandatory = $true)][Collections.Generic.List[string]]$Lines,
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
        [Parameter(Mandatory = $true)][Collections.Generic.List[string]]$Lines,
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
        [Parameter(Mandatory = $true)][Collections.Generic.List[string]]$Lines,
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
        [Parameter(Mandatory = $true)][Collections.Generic.List[string]]$Lines,
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
        [Parameter(Mandatory = $true)][Collections.Generic.List[string]]$Lines,
        [Parameter(Mandatory = $true)][string]$BaseUrl,
        [switch]$AllowExistingManaged
    )

    $providerPattern = [regex]::Escape($script:ManagedProviderId)
    if ($Lines | Where-Object { $_ -match ("^\s*\[model_providers\.$providerPattern\.auth\]\s*(?:#.*)?$") }) {
        throw "config.toml already contains [model_providers.$($script:ManagedProviderId).auth]. Remove or migrate that table before using the env_key-based switcher."
    }

    $headerIndices = [Collections.Generic.List[int]]::new()
    for ($i = 0; $i -lt $Lines.Count; $i++) {
        if ($Lines[$i] -match ("^\s*\[model_providers\.$providerPattern\]\s*(?:#.*)?$")) {
            $headerIndices.Add($i)
        }
    }
    if ($headerIndices.Count -gt 1) {
        throw "config.toml contains more than one [model_providers.$($script:ManagedProviderId)] table."
    }
    if ($headerIndices.Count -eq 1 -and -not $AllowExistingManaged) {
        throw "config.toml already contains [model_providers.$($script:ManagedProviderId)] without active switcher state. Refusing to overwrite a provider the switcher cannot prove it owns."
    }

    $desired = [ordered]@{
        name = 'name = "RCSL AI Nexus"'
        base_url = ('base_url = "{0}/v1"' -f (Escape-TomlString -Value $BaseUrl.TrimEnd('/')))
        env_key = 'env_key = "RCSL_API_KEY"'
        wire_api = 'wire_api = "responses"'
    }

    if ($headerIndices.Count -eq 0) {
        if ($Lines.Count -gt 0 -and $Lines[$Lines.Count - 1] -ne '') {
            $Lines.Add('')
        }
        $Lines.Add("[model_providers.$($script:ManagedProviderId)]")
        foreach ($line in $desired.Values) {
            $Lines.Add($line)
        }
        return
    }

    $start = $headerIndices[0]
    $end = $Lines.Count
    for ($i = $start + 1; $i -lt $Lines.Count; $i++) {
        if ($Lines[$i] -match '^\s*\[[A-Za-z0-9_.-]+\]\s*(?:#.*)?$') {
            $end = $i
            break
        }
    }

    foreach ($incompatibleKey in @('experimental_bearer_token')) {
        for ($i = $start + 1; $i -lt $end; $i++) {
            if ($Lines[$i] -match ('^\s*{0}\s*=' -f [regex]::Escape($incompatibleKey))) {
                throw "[model_providers.$($script:ManagedProviderId)] already defines '$incompatibleKey', which cannot be combined with env_key. Remove or migrate it before using the switcher."
            }
        }
    }
    for ($i = $start + 1; $i -lt $end; $i++) {
        if ($Lines[$i] -match '^\s*requires_openai_auth\s*=\s*true\s*(?:#.*)?$') {
            throw "[model_providers.$($script:ManagedProviderId)] requires OpenAI authentication and cannot be used with the switcher's env_key authentication."
        }
    }

    foreach ($key in $desired.Keys) {
        $matches = [Collections.Generic.List[int]]::new()
        for ($i = $start + 1; $i -lt $end; $i++) {
            if ($Lines[$i] -match ('^\s*{0}\s*=' -f [regex]::Escape($key))) {
                $matches.Add($i)
            }
        }
        if ($matches.Count -gt 1) {
            throw "[model_providers.$($script:ManagedProviderId)] contains more than one '$key' key."
        }
        if ($matches.Count -eq 1) {
            $Lines[$matches[0]] = $desired[$key]
        }
        else {
            $Lines.Insert($end, $desired[$key])
            $end++
        }
    }
}

function Get-ManagedProjectionSha256 {
    param([Parameter(Mandatory = $true)][Collections.Generic.List[string]]$Lines)
    $projection = [Collections.Generic.List[string]]::new()
    foreach ($key in @('model', 'model_provider')) {
        $indices = Find-TopLevelKeyIndices -Lines $Lines -Key $key
        if ($indices.Count -eq 1) {
            $projection.Add($Lines[$indices[0]].Trim())
        }
    }
    $providerPattern = [regex]::Escape($script:ManagedProviderId)
    for ($i = 0; $i -lt $Lines.Count; $i++) {
        if ($Lines[$i] -match ("^\s*\[model_providers\.$providerPattern\]\s*(?:#.*)?$")) {
            for ($j = $i; $j -lt $Lines.Count; $j++) {
                if ($j -gt $i -and $Lines[$j] -match '^\s*\[[A-Za-z0-9_.-]+\]\s*(?:#.*)?$') {
                    break
                }
                $projection.Add($Lines[$j].Trim())
            }
            break
        }
    }
    return (Get-TextSha256 -Text ([string]::Join("`n", $projection.ToArray())))
}

function Get-ManagedProviderIssues {
    param([Parameter(Mandatory = $true)][Collections.Generic.List[string]]$Lines)
    $issues = [Collections.Generic.List[string]]::new()
    $providerPattern = [regex]::Escape($script:ManagedProviderId)
    $start = -1
    for ($i = 0; $i -lt $Lines.Count; $i++) {
        if ($Lines[$i] -match ("^\s*\[model_providers\.$providerPattern\]\s*(?:#.*)?$")) {
            if ($start -ne -1) {
                $issues.Add("Duplicate [model_providers.$($script:ManagedProviderId)] tables were found.")
            }
            $start = $i
        }
    }
    if ($start -eq -1) {
        return @($issues)
    }
    $end = $Lines.Count
    for ($i = $start + 1; $i -lt $Lines.Count; $i++) {
        if ($Lines[$i] -match '^\s*\[[A-Za-z0-9_.-]+\]\s*(?:#.*)?$') {
            $end = $i
            break
        }
    }
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
    return @($issues)
}

function New-ConfigBackup {
    param(
        [Parameter(Mandatory = $true)][string]$ConfigPath,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Text
    )
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
    return (Get-Content -Raw -LiteralPath $path | ConvertFrom-Json)
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
        $ids = @()
        if ($null -ne $response.data) {
            $ids = @($response.data | ForEach-Object { [string]$_.id })
        }
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

    if ($ValidateGateway) {
        [void](Test-RcslGateway -ApiKey $ApiKey -BaseUrl $BaseUrl -Capability $Capability)
    }

    Stop-CodexAppGracefully -TimeoutSeconds $CloseTimeoutSeconds

    $configPath = Get-CodexConfigPath
    $originalText = Read-Utf8Text -Path $configPath
    $parts = Split-TomlLines -Text $originalText
    Assert-SafeTomlForManagedEdit -Lines $parts.Lines
    $state = Get-SwitcherState
    if ($null -ne $state) {
        $schemaProperty = $state.PSObject.Properties['SchemaVersion']
        if ($null -eq $schemaProperty -or [int]$schemaProperty.Value -ne $script:StateSchemaVersion) {
            throw 'Switcher recovery state is missing a supported schema version. Preserve it and recover manually; the switcher will not overwrite unknown state.'
        }
    }
    $activeState = ($null -ne $state -and [string]$state.Mode -in @('preparing-rcsl', 'rcsl'))
    $ownedState = ($null -ne $state -and $null -ne $state.PSObject.Properties['ProviderId'] -and [string]$state.ProviderId -eq $script:ManagedProviderId)
    if ($activeState -and [string]$state.ConfigPath -ne $configPath) {
        throw "The switcher has an active RCSL session for '$($state.ConfigPath)', but CODEX_HOME now resolves to '$configPath'. Restore OpenAI with the original CODEX_HOME before switching another profile."
    }
    $captureOriginal = -not $activeState
    $originalModel = Get-OriginalTopLevelKey -Lines $parts.Lines -Key 'model'
    $originalModelProvider = Get-OriginalTopLevelKey -Lines $parts.Lines -Key 'model_provider'
    if (-not $activeState -and (Get-TopLevelTomlValue -Lines $parts.Lines -Key 'model_provider') -eq $script:ManagedProviderId) {
        throw 'The managed provider is selected while recovery state says the previous switch is inactive. Use Switch App back to OpenAI first so the recorded original selection is reconciled.'
    }

    Set-TopLevelTomlKey -Lines $parts.Lines -Key 'model_provider' -Line ('model_provider = "{0}"' -f $script:ManagedProviderId)
    Set-TopLevelTomlKey -Lines $parts.Lines -Key 'model' -Line ('model = "{0}"' -f (Escape-TomlString -Value $Capability))
    Set-RcslProviderTable -Lines $parts.Lines -BaseUrl $BaseUrl -AllowExistingManaged:($activeState -or $ownedState)
    $updatedText = Join-TomlLines -Lines $parts.Lines -Newline $parts.Newline -TrailingNewline $true

    if ($captureOriginal) {
        $backupPath = New-ConfigBackup -ConfigPath $configPath -Text $originalText
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

    Stop-CodexAppGracefully -TimeoutSeconds $CloseTimeoutSeconds

    $state = Get-SwitcherState
    $configPath = Get-CodexConfigPath
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
        if ($null -ne $state.PSObject.Properties['ProviderId'] -and [string]$state.ProviderId -eq $script:ManagedProviderId) {
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
        return @()
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
    return @($paths)
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
    $model = Get-TopLevelTomlValue -Lines $parts.Lines -Key 'model'
    $provider = Get-TopLevelTomlValue -Lines $parts.Lines -Key 'model_provider'
    $providerPattern = [regex]::Escape($script:ManagedProviderId)
    $hasProviderTable = [bool]($parts.Lines | Where-Object { $_ -match ("^\s*\[model_providers\.$providerPattern\]\s*(?:#.*)?$") })
    if ($provider -eq $script:ManagedProviderId -and -not $hasProviderTable) {
        $issues.Add("model_provider selects $($script:ManagedProviderId), but its provider table is absent.")
    }
    if ($hasProviderTable) {
        foreach ($providerIssue in @(Get-ManagedProviderIssues -Lines $parts.Lines)) {
            $issues.Add($providerIssue)
        }
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
                    $managedHashMatchesState = ([string]$hashProperty.Value -eq (Get-ManagedProjectionSha256 -Lines $parts.Lines))
                    if (-not $managedHashMatchesState) {
                        $issues.Add('The managed model/provider projection has drifted since the switch was recorded.')
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
    $projectConfigs = @(Get-ProjectConfigPaths -ProjectPath $ProjectPath)
    return [pscustomobject]@{
        IsWindows = ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT)
        AppInstalled = $app.Installed
        AppVersion = $app.Version
        AppRunning = (@(Get-CodexAppProcesses).Count -gt 0)
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
    'Get-CodexConfigPath',
    'Get-CodexSwitcherStatus',
    'Get-SwitcherState',
    'Install-CodexApp',
    'Stop-CodexAppGracefully',
    'Test-RcslGateway'
)
