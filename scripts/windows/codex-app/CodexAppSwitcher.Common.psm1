Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:CodexPackageName = 'OpenAI.Codex'
$script:CodexStoreId = '9PLM9XGG6VKS'
$script:DefaultGatewayBaseUrl = 'https://llmapi.rcsl.online'
$script:DefaultCapability = 'code'
$script:StateSchemaVersion = 1

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
    return @($processes | Where-Object {
        try {
            -not [string]::IsNullOrWhiteSpace($_.Path) -and
                $_.Path.StartsWith($installRoot, [StringComparison]::OrdinalIgnoreCase)
        }
        catch {
            $false
        }
    })
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

function Find-TopLevelKeyIndices {
    param(
        [Parameter(Mandatory = $true)][Collections.Generic.List[string]]$Lines,
        [Parameter(Mandatory = $true)][ValidateSet('model', 'model_provider')][string]$Key
    )
    $indices = [Collections.Generic.List[int]]::new()
    for ($i = 0; $i -lt $Lines.Count; $i++) {
        if ($Lines[$i] -match '^\s*\[') {
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

function Set-RcslProviderTable {
    param(
        [Parameter(Mandatory = $true)][Collections.Generic.List[string]]$Lines,
        [Parameter(Mandatory = $true)][string]$BaseUrl
    )

    if ($Lines | Where-Object { $_ -match '^\s*\[model_providers\.rcsl\.auth\]\s*$' }) {
        throw 'config.toml already contains [model_providers.rcsl.auth]. Remove or migrate that table before using the env_key-based switcher.'
    }

    $headerIndices = [Collections.Generic.List[int]]::new()
    for ($i = 0; $i -lt $Lines.Count; $i++) {
        if ($Lines[$i] -match '^\s*\[model_providers\.rcsl\]\s*$') {
            $headerIndices.Add($i)
        }
    }
    if ($headerIndices.Count -gt 1) {
        throw 'config.toml contains more than one [model_providers.rcsl] table.'
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
        $Lines.Add('[model_providers.rcsl]')
        foreach ($line in $desired.Values) {
            $Lines.Add($line)
        }
        return
    }

    $start = $headerIndices[0]
    $end = $Lines.Count
    for ($i = $start + 1; $i -lt $Lines.Count; $i++) {
        if ($Lines[$i] -match '^\s*\[') {
            $end = $i
            break
        }
    }

    foreach ($incompatibleKey in @('experimental_bearer_token', 'requires_openai_auth')) {
        for ($i = $start + 1; $i -lt $end; $i++) {
            if ($Lines[$i] -match ('^\s*{0}\s*=' -f [regex]::Escape($incompatibleKey))) {
                throw "[model_providers.rcsl] already defines '$incompatibleKey', which cannot be combined with env_key. Remove or migrate it before using the switcher."
            }
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
            throw "[model_providers.rcsl] contains more than one '$key' key."
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

function New-ConfigBackup {
    param(
        [Parameter(Mandatory = $true)][string]$ConfigPath,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Text
    )
    $backupDirectory = Join-Path (Get-SwitcherStateDirectory) 'backups'
    New-DirectoryIfMissing -Path $backupDirectory
    $stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')
    $backupPath = Join-Path $backupDirectory ("config.toml.before-rcsl-$stamp")
    Write-Utf8TextAtomic -Path $backupPath -Text $Text
    return $backupPath
}

function Save-SwitcherState {
    param([Parameter(Mandatory = $true)]$State)
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

function Test-RcslGateway {
    param(
        [Parameter(Mandatory = $true)][Security.SecureString]$ApiKey,
        [string]$BaseUrl = $script:DefaultGatewayBaseUrl,
        [string]$Capability = $script:DefaultCapability,
        [ValidateRange(5, 120)][int]$TimeoutSeconds = 30
    )
    $uri = $null
    if (-not [Uri]::TryCreate($BaseUrl, [UriKind]::Absolute, [ref]$uri) -or $uri.Scheme -ne 'https') {
        throw 'The gateway base URL must be an absolute HTTPS URL.'
    }

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

function Enable-RcslCodexApp {
    param(
        [Parameter(Mandatory = $true)][Security.SecureString]$ApiKey,
        [string]$BaseUrl = $script:DefaultGatewayBaseUrl,
        [string]$Capability = $script:DefaultCapability,
        [switch]$InstallIfMissing,
        [switch]$ValidateGateway,
        [ValidateRange(5, 120)][int]$CloseTimeoutSeconds = 30
    )
    Assert-Windows

    $uri = $null
    if (-not [Uri]::TryCreate($BaseUrl, [UriKind]::Absolute, [ref]$uri) -or $uri.Scheme -ne 'https') {
        throw 'The gateway base URL must be an absolute HTTPS URL.'
    }
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
    $state = Get-SwitcherState
    $activeState = ($null -ne $state -and [string]$state.Mode -in @('preparing-rcsl', 'rcsl'))
    if ($activeState -and [string]$state.ConfigPath -ne $configPath) {
        throw "The switcher has an active RCSL session for '$($state.ConfigPath)', but CODEX_HOME now resolves to '$configPath'. Restore OpenAI with the original CODEX_HOME before switching another profile."
    }
    $captureOriginal = -not $activeState

    if ($captureOriginal) {
        $backupPath = New-ConfigBackup -ConfigPath $configPath -Text $originalText
        $state = [pscustomobject]@{
            SchemaVersion = $script:StateSchemaVersion
            Mode = 'preparing-rcsl'
            ConfigPath = $configPath
            BackupPath = $backupPath
            ConfigSha256Before = Get-TextSha256 -Text $originalText
            OriginalModel = Get-OriginalTopLevelKey -Lines $parts.Lines -Key 'model'
            OriginalModelProvider = Get-OriginalTopLevelKey -Lines $parts.Lines -Key 'model_provider'
            GatewayBaseUrl = $BaseUrl.TrimEnd('/')
            Capability = $Capability
            AppVersion = $app.Version
            SwitchedAtUtc = [DateTime]::UtcNow.ToString('o')
        }
        Save-SwitcherState -State $state
    }

    Set-TopLevelTomlKey -Lines $parts.Lines -Key 'model_provider' -Line ('model_provider = "{0}"' -f 'rcsl')
    Set-TopLevelTomlKey -Lines $parts.Lines -Key 'model' -Line ('model = "{0}"' -f (Escape-TomlString -Value $Capability))
    Set-RcslProviderTable -Lines $parts.Lines -BaseUrl $BaseUrl
    $updatedText = Join-TomlLines -Lines $parts.Lines -Newline $parts.Newline -TrailingNewline $true
    Write-Utf8TextAtomic -Path $configPath -Text $updatedText

    $state.Mode = 'rcsl'
    $state.GatewayBaseUrl = $BaseUrl.TrimEnd('/')
    $state.Capability = $Capability
    $state.AppVersion = $app.Version
    Set-StateProperty -State $state -Name 'ConfigSha256After' -Value (Get-TextSha256 -Text $updatedText)
    Save-SwitcherState -State $state

    $process = Start-CodexAppWithEnvironment -ExecutablePath $app.ExecutablePath -ApiKey $ApiKey
    return [pscustomobject]@{
        Mode = 'rcsl'
        AppVersion = $app.Version
        ProcessId = $process.Id
        ConfigPath = $configPath
        BackupPath = $state.BackupPath
        GatewayBaseUrl = $BaseUrl.TrimEnd('/')
        Capability = $Capability
    }
}

function Disable-RcslCodexApp {
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
    $activeState = ($null -ne $state -and [string]$state.Mode -in @('preparing-rcsl', 'rcsl'))
    if ($activeState -and [string]$state.ConfigPath -ne $configPath) {
        throw "The active RCSL session belongs to '$($state.ConfigPath)', but CODEX_HOME now resolves to '$configPath'. Restore the original CODEX_HOME value and retry."
    }
    $text = Read-Utf8Text -Path $configPath
    $parts = Split-TomlLines -Text $text

    if ($activeState -and [int]$state.SchemaVersion -eq $script:StateSchemaVersion) {
        Restore-TopLevelTomlKey -Lines $parts.Lines -Key 'model' -Original $state.OriginalModel
        Restore-TopLevelTomlKey -Lines $parts.Lines -Key 'model_provider' -Original $state.OriginalModelProvider
        $state.Mode = 'openai'
        Set-StateProperty -State $state -Name 'RestoredAtUtc' -Value ([DateTime]::UtcNow.ToString('o'))
        $state.AppVersion = $app.Version
    }
    elseif ($null -ne $state -and [string]$state.Mode -eq 'openai' -and [int]$state.SchemaVersion -eq $script:StateSchemaVersion) {
        Set-StateProperty -State $state -Name 'RestoredAtUtc' -Value ([DateTime]::UtcNow.ToString('o'))
        $state.AppVersion = $app.Version
    }
    else {
        $modelProviderIndices = Find-TopLevelKeyIndices -Lines $parts.Lines -Key 'model_provider'
        if ($modelProviderIndices.Count -eq 1 -and $parts.Lines[$modelProviderIndices[0]] -match '^\s*model_provider\s*=\s*["'']rcsl["'']\s*$') {
            $parts.Lines.RemoveAt($modelProviderIndices[0])
        }
        $modelIndices = Find-TopLevelKeyIndices -Lines $parts.Lines -Key 'model'
        if ($modelIndices.Count -eq 1 -and $parts.Lines[$modelIndices[0]] -match '^\s*model\s*=\s*["'']code["'']\s*$') {
            $parts.Lines.RemoveAt($modelIndices[0])
        }
        $state = [pscustomobject]@{
            SchemaVersion = $script:StateSchemaVersion
            Mode = 'openai'
            ConfigPath = $configPath
            BackupPath = ''
            AppVersion = $app.Version
            RestoredAtUtc = [DateTime]::UtcNow.ToString('o')
            Recovery = 'No prior switcher state existed; only exact rcsl/code top-level selections were removed.'
        }
    }

    $updatedText = Join-TomlLines -Lines $parts.Lines -Newline $parts.Newline -TrailingNewline $true
    Write-Utf8TextAtomic -Path $configPath -Text $updatedText
    Set-StateProperty -State $state -Name 'ConfigSha256AfterRestore' -Value (Get-TextSha256 -Text $updatedText)
    Save-SwitcherState -State $state

    if ($RemovePersistedUserKey) {
        [Environment]::SetEnvironmentVariable('RCSL_API_KEY', $null, 'User')
    }

    $process = Start-CodexAppWithEnvironment -ExecutablePath $app.ExecutablePath
    return [pscustomobject]@{
        Mode = 'openai'
        AppVersion = $app.Version
        ProcessId = $process.Id
        ConfigPath = $configPath
        ProviderDefinitionPreserved = $true
        PersistedUserKeyRemoved = [bool]$RemovePersistedUserKey
    }
}

function Get-CodexSwitcherStatus {
    Assert-Windows
    $app = Get-CodexAppInfo
    $configPath = Get-CodexConfigPath
    $text = Read-Utf8Text -Path $configPath
    $parts = Split-TomlLines -Text $text
    $model = ''
    $provider = ''
    $modelIndices = Find-TopLevelKeyIndices -Lines $parts.Lines -Key 'model'
    $providerIndices = Find-TopLevelKeyIndices -Lines $parts.Lines -Key 'model_provider'
    if ($modelIndices.Count -eq 1 -and $parts.Lines[$modelIndices[0]] -match '^\s*model\s*=\s*["'']([^"'']+)["'']') {
        $model = $Matches[1]
    }
    if ($providerIndices.Count -eq 1 -and $parts.Lines[$providerIndices[0]] -match '^\s*model_provider\s*=\s*["'']([^"'']+)["'']') {
        $provider = $Matches[1]
    }
    $hasProviderTable = [bool]($parts.Lines | Where-Object { $_ -match '^\s*\[model_providers\.rcsl\]\s*$' })
    $state = Get-SwitcherState
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
        EffectiveMode = if ($provider -eq 'rcsl') { 'rcsl' } else { 'openai-or-default' }
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
