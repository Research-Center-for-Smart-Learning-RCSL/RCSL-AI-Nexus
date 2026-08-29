[CmdletBinding()]
param(
    [string]$BaseUrl = 'https://llmapi.rcsl.online',
    [string]$Capability = 'code',
    [string]$ProjectPath = (Get-Location).Path,
    [switch]$Online,
    [switch]$Authenticated,
    [switch]$AsJson
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'CodexAppSwitcher.Common.psm1') -Force

$results = [Collections.Generic.List[object]]::new()

function Read-NexusKeyFromDialog {
    if ([Threading.Thread]::CurrentThread.ApartmentState -ne [Threading.ApartmentState]::STA) {
        throw 'Authenticated Doctor checks require an STA PowerShell process so the masked Windows dialog can be shown. Launch with powershell.exe -STA.'
    }
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    $dialog = New-Object Windows.Forms.Form
    $dialog.Text = 'RCSL AI Nexus - Doctor authentication'
    $dialog.StartPosition = 'CenterScreen'
    $dialog.ClientSize = New-Object Drawing.Size(540, 155)
    $dialog.FormBorderStyle = 'FixedDialog'
    $dialog.MaximizeBox = $false
    $dialog.MinimizeBox = $false

    $label = New-Object Windows.Forms.Label
    $label.Text = 'Nexus API key (never passed on the command line or persisted)'
    $label.Location = New-Object Drawing.Point(18, 18)
    $label.AutoSize = $true
    $dialog.Controls.Add($label)

    $keyBox = New-Object Windows.Forms.TextBox
    $keyBox.Location = New-Object Drawing.Point(21, 47)
    $keyBox.Size = New-Object Drawing.Size(498, 25)
    $keyBox.UseSystemPasswordChar = $true
    $dialog.Controls.Add($keyBox)

    $okButton = New-Object Windows.Forms.Button
    $okButton.Text = 'Run authenticated check'
    $okButton.Location = New-Object Drawing.Point(325, 95)
    $okButton.Size = New-Object Drawing.Size(194, 32)
    $okButton.DialogResult = [Windows.Forms.DialogResult]::OK
    $dialog.Controls.Add($okButton)
    $dialog.AcceptButton = $okButton

    $cancelButton = New-Object Windows.Forms.Button
    $cancelButton.Text = 'Cancel'
    $cancelButton.Location = New-Object Drawing.Point(229, 95)
    $cancelButton.Size = New-Object Drawing.Size(86, 32)
    $cancelButton.DialogResult = [Windows.Forms.DialogResult]::Cancel
    $dialog.Controls.Add($cancelButton)
    $dialog.CancelButton = $cancelButton

    $dialog.Add_Shown({ $keyBox.Focus() })
    try {
        if ($dialog.ShowDialog() -ne [Windows.Forms.DialogResult]::OK -or [string]::IsNullOrWhiteSpace($keyBox.Text)) {
            throw 'Authenticated Doctor check was cancelled or no API key was entered.'
        }
        return (ConvertTo-SecureString -String $keyBox.Text.Trim() -AsPlainText -Force)
    }
    finally {
        $keyBox.Clear()
        $dialog.Dispose()
    }
}

function Add-Check {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][ValidateSet('PASS', 'WARN', 'FAIL', 'SKIP')][string]$Status,
        [Parameter(Mandatory = $true)][string]$Detail
    )
    $results.Add([pscustomobject]@{
        Check = $Name
        Status = $Status
        Detail = $Detail
    })
}

function Invoke-Check {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][scriptblock]$Action
    )
    try {
        & $Action
    }
    catch {
        Add-Check -Name $Name -Status 'FAIL' -Detail $_.Exception.Message
    }
}

Invoke-Check -Name 'Operating system' -Action {
    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
        throw 'This doctor supports Windows only.'
    }
    Add-Check -Name 'Operating system' -Status 'PASS' -Detail ([Environment]::OSVersion.VersionString)
}

Invoke-Check -Name 'Codex App installation' -Action {
    $script:app = Get-CodexAppInfo
    if (-not $script:app.Installed) {
        throw 'OpenAI.Codex is not installed. Run Start-CodexAppSwitcher.ps1; it can install the Microsoft Store package with winget.'
    }
    Add-Check -Name 'Codex App installation' -Status 'PASS' -Detail ("Version {0}; discovered by {1}" -f $script:app.Version, $script:app.Discovery)
}

Invoke-Check -Name 'Codex App process' -Action {
    $count = @(Get-CodexAppProcesses).Count
    if ($count -eq 0) {
        Add-Check -Name 'Codex App process' -Status 'WARN' -Detail 'The App is not running. This is expected before a switch, but no App-specific state can be observed.'
    }
    else {
        Add-Check -Name 'Codex App process' -Status 'PASS' -Detail "$count ChatGPT process(es) are running."
    }
}

$status = $null
Invoke-Check -Name 'Codex configuration' -Action {
    $script:status = Get-CodexSwitcherStatus -ProjectPath $ProjectPath
    if (-not $script:status.ConfigExists) {
        Add-Check -Name 'Codex configuration' -Status 'WARN' -Detail "No config.toml exists at $($script:status.ConfigPath); Codex will use built-in defaults."
    }
    else {
        $issueCount = @($script:status.ConfigurationIssues).Count
        if ($issueCount -gt 0) {
            throw ([string]::Join(' ', [string[]]$script:status.ConfigurationIssues))
        }
        Add-Check -Name 'Codex configuration' -Status 'PASS' -Detail ("User-level default: {0}; model_provider={1}; model={2}" -f $script:status.ConfigPath, $script:status.ModelProvider, $script:status.Model)
    }
}

Invoke-Check -Name 'Project model override' -Action {
    if ($null -eq $script:status) {
        throw 'Configuration status was unavailable.'
    }
    if (-not (Test-Path -LiteralPath $ProjectPath -PathType Container)) {
        throw "ProjectPath is not an existing directory: $ProjectPath"
    }
    $projectConfigs = @($script:status.HigherPrecedenceProjectConfigs)
    if ($projectConfigs.Count -gt 0) {
        Add-Check -Name 'Project model override' -Status 'WARN' -Detail ("Project config defines a top-level model that can override the user-level Nexus capability: {0}. Project-local provider keys are ignored by Codex." -f ($projectConfigs -join ', '))
    }
    else {
        Add-Check -Name 'Project model override' -Status 'PASS' -Detail "No project .codex\config.toml from '$ProjectPath' through its ancestors defines a top-level model override."
    }
}

Invoke-Check -Name 'RCSL provider definition' -Action {
    if ($null -eq $script:status) {
        throw 'Configuration status was unavailable.'
    }
    if ($script:status.RcslProviderDefined) {
        Add-Check -Name 'RCSL provider definition' -Status 'PASS' -Detail ("[model_providers.{0}] is present; managed projection matches state: {1}" -f $script:status.ManagedProviderId, $script:status.ManagedHashMatchesState)
    }
    elseif ($script:status.ModelProvider -eq $script:status.ManagedProviderId) {
        throw "model_provider selects $($script:status.ManagedProviderId), but its provider table is absent."
    }
    else {
        Add-Check -Name 'RCSL provider definition' -Status 'WARN' -Detail 'The provider has not been configured yet.'
    }
}

Invoke-Check -Name 'Switcher recovery state' -Action {
    if ($null -eq $script:status -or $null -eq $script:status.State) {
        Add-Check -Name 'Switcher recovery state' -Status 'WARN' -Detail 'No switcher state exists. This is normal before the first switch; do not delete config.toml to recover manually.'
    }
    else {
        $backupProperty = $script:status.State.PSObject.Properties['BackupPath']
        $backup = if ($null -eq $backupProperty) { '' } else { [string]$backupProperty.Value }
        if (-not [string]::IsNullOrWhiteSpace($backup) -and -not (Test-Path -LiteralPath $backup)) {
            throw "Switcher state names a missing backup: $backup"
        }
        Add-Check -Name 'Switcher recovery state' -Status 'PASS' -Detail ("Recorded mode: {0}; backup: {1}" -f $script:status.State.Mode, $backup)
    }
}

Invoke-Check -Name 'Persistent Nexus key' -Action {
    if ($null -eq $script:status) {
        throw 'Configuration status was unavailable.'
    }
    if ($script:status.PersistedMachineKeyPresent) {
        Add-Check -Name 'Persistent Nexus key' -Status 'WARN' -Detail 'A machine-level RCSL_API_KEY exists. Remove it from an elevated shell if it is no longer intentional.'
    }
    elseif ($script:status.PersistedUserKeyPresent) {
        Add-Check -Name 'Persistent Nexus key' -Status 'WARN' -Detail 'A user-level RCSL_API_KEY exists, probably from legacy setx instructions. The switcher does not create one.'
    }
    else {
        Add-Check -Name 'Persistent Nexus key' -Status 'PASS' -Detail 'No user- or machine-level RCSL_API_KEY is stored.'
    }
}

if ($Online) {
    Invoke-Check -Name 'Gateway URL' -Action {
        # The same normalizer the switch path uses, so a URL the Doctor passes is a
        # URL a switch will accept.
        Add-Check -Name 'Gateway URL' -Status 'PASS' -Detail (Get-NormalizedGatewayBaseUrl -BaseUrl $BaseUrl)
    }

    Invoke-Check -Name 'DNS resolution' -Action {
        $uri = [Uri]$BaseUrl
        $addresses = [Net.Dns]::GetHostAddresses($uri.DnsSafeHost)
        if ($addresses.Count -eq 0) {
            throw "No address was returned for $($uri.DnsSafeHost)."
        }
        Add-Check -Name 'DNS resolution' -Status 'PASS' -Detail (($addresses | ForEach-Object { $_.IPAddressToString }) -join ', ')
    }

    Invoke-Check -Name 'HTTPS health endpoint' -Action {
        $healthUri = '{0}/healthz' -f $BaseUrl.TrimEnd('/')
        $response = Invoke-WebRequest -Method Get -Uri $healthUri -UseBasicParsing -TimeoutSec 20
        if ($response.StatusCode -ne 200) {
            throw "GET /healthz returned HTTP $($response.StatusCode)."
        }
        Add-Check -Name 'HTTPS health endpoint' -Status 'PASS' -Detail 'GET /healthz returned HTTP 200 with a trusted TLS connection.'
    }
}
else {
    Add-Check -Name 'Online checks' -Status 'SKIP' -Detail 'Pass -Online to check DNS, TLS, and /healthz.'
}

if ($Authenticated) {
    $secureKey = $null
    try {
        $secureKey = Read-NexusKeyFromDialog
        Invoke-Check -Name 'Authenticated model catalogue' -Action {
            $gateway = Test-RcslGateway -ApiKey $secureKey -BaseUrl $BaseUrl -Capability $Capability
            Add-Check -Name 'Authenticated model catalogue' -Status 'PASS' -Detail ("GET /v1/models includes '{0}'." -f $gateway.Capability)
        }
    }
    finally {
        if ($null -ne $secureKey) {
            $secureKey.Dispose()
        }
    }
}
else {
    Add-Check -Name 'Authenticated model catalogue' -Status 'SKIP' -Detail 'Pass -Authenticated to prompt securely for a key and check GET /v1/models.'
}

Add-Check -Name 'Full App agent loop' -Status 'WARN' -Detail 'Not automated: create a new App task and request a file read. CLI or HTTP checks do not prove the App-specific plugin and model-picker path.'

if ($AsJson) {
    $results | ConvertTo-Json -Depth 5
}
else {
    $results | Format-Table -AutoSize -Wrap
}

if (@($results | Where-Object { $_.Status -eq 'FAIL' }).Count -gt 0) {
    exit 1
}
