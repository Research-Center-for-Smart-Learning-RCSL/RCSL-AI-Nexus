[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'The Codex App switcher supports Windows only.'
}

if ([Threading.Thread]::CurrentThread.ApartmentState -ne [Threading.ApartmentState]::STA) {
    $hostPath = (Get-Command powershell.exe -ErrorAction Stop).Path
    Start-Process -FilePath $hostPath -ArgumentList @('-NoProfile', '-STA', '-File', ('"{0}"' -f $PSCommandPath))
    return
}

Import-Module (Join-Path $PSScriptRoot 'CodexAppSwitcher.Common.psm1') -Force
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()

$form = New-Object Windows.Forms.Form
$form.Text = 'RCSL AI Nexus - Codex App Switcher'
$form.StartPosition = 'CenterScreen'
$form.ClientSize = New-Object Drawing.Size(720, 620)
$form.MinimumSize = New-Object Drawing.Size(736, 659)
$form.Font = New-Object Drawing.Font('Segoe UI', 9)

$title = New-Object Windows.Forms.Label
$title.Text = 'Switch the Windows Codex App provider safely'
$title.Font = New-Object Drawing.Font('Segoe UI Semibold', 16)
$title.AutoSize = $true
$title.Location = New-Object Drawing.Point(24, 20)
$form.Controls.Add($title)

$description = New-Object Windows.Forms.Label
$description.Text = 'The switcher closes Codex App gracefully, backs up config.toml, changes only the provider selection, and restarts the app. It never logs or stores the Nexus API key.'
$description.Location = New-Object Drawing.Point(27, 58)
$description.Size = New-Object Drawing.Size(660, 45)
$form.Controls.Add($description)

$modeLabel = New-Object Windows.Forms.Label
$modeLabel.Text = 'Current state: loading...'
$modeLabel.Font = New-Object Drawing.Font('Segoe UI Semibold', 10)
$modeLabel.Location = New-Object Drawing.Point(27, 105)
$modeLabel.Size = New-Object Drawing.Size(660, 25)
$form.Controls.Add($modeLabel)

$baseUrlLabel = New-Object Windows.Forms.Label
$baseUrlLabel.Text = 'Gateway base URL'
$baseUrlLabel.Location = New-Object Drawing.Point(27, 145)
$baseUrlLabel.AutoSize = $true
$form.Controls.Add($baseUrlLabel)

$baseUrlBox = New-Object Windows.Forms.TextBox
$baseUrlBox.Text = 'https://llmapi.rcsl.online'
$baseUrlBox.Location = New-Object Drawing.Point(190, 141)
$baseUrlBox.Size = New-Object Drawing.Size(497, 25)
$form.Controls.Add($baseUrlBox)

$capabilityLabel = New-Object Windows.Forms.Label
$capabilityLabel.Text = 'Capability'
$capabilityLabel.Location = New-Object Drawing.Point(27, 183)
$capabilityLabel.AutoSize = $true
$form.Controls.Add($capabilityLabel)

$capabilityBox = New-Object Windows.Forms.TextBox
$capabilityBox.Text = 'code'
$capabilityBox.Location = New-Object Drawing.Point(190, 179)
$capabilityBox.Size = New-Object Drawing.Size(180, 25)
$form.Controls.Add($capabilityBox)

$projectPathLabel = New-Object Windows.Forms.Label
$projectPathLabel.Text = 'Project directory for Doctor'
$projectPathLabel.Location = New-Object Drawing.Point(27, 221)
$projectPathLabel.AutoSize = $true
$form.Controls.Add($projectPathLabel)

$projectPathBox = New-Object Windows.Forms.TextBox
$projectPathBox.Text = (Get-Location).Path
$projectPathBox.Location = New-Object Drawing.Point(190, 217)
$projectPathBox.Size = New-Object Drawing.Size(497, 25)
$form.Controls.Add($projectPathBox)

$apiKeyLabel = New-Object Windows.Forms.Label
$apiKeyLabel.Text = 'Nexus API key'
$apiKeyLabel.Location = New-Object Drawing.Point(27, 259)
$apiKeyLabel.AutoSize = $true
$form.Controls.Add($apiKeyLabel)

$apiKeyBox = New-Object Windows.Forms.TextBox
$apiKeyBox.Location = New-Object Drawing.Point(190, 255)
$apiKeyBox.Size = New-Object Drawing.Size(497, 25)
$apiKeyBox.UseSystemPasswordChar = $true
$form.Controls.Add($apiKeyBox)

$keyNote = New-Object Windows.Forms.Label
$keyNote.Text = 'The key is not persisted. It is validated and passed only to the newly started App process.'
$keyNote.ForeColor = [Drawing.Color]::DimGray
$keyNote.Location = New-Object Drawing.Point(190, 284)
$keyNote.Size = New-Object Drawing.Size(497, 35)
$form.Controls.Add($keyNote)

$validateCheck = New-Object Windows.Forms.CheckBox
$validateCheck.Text = 'Validate GET /v1/models before changing the App'
$validateCheck.Checked = $true
$validateCheck.Location = New-Object Drawing.Point(190, 316)
$validateCheck.Size = New-Object Drawing.Size(420, 25)
$form.Controls.Add($validateCheck)

$removeLegacyCheck = New-Object Windows.Forms.CheckBox
$removeLegacyCheck.Text = 'When switching back, remove a legacy user-level RCSL_API_KEY created with setx'
$removeLegacyCheck.Checked = $false
$removeLegacyCheck.Location = New-Object Drawing.Point(190, 344)
$removeLegacyCheck.Size = New-Object Drawing.Size(497, 40)
$form.Controls.Add($removeLegacyCheck)

$connectButton = New-Object Windows.Forms.Button
$connectButton.Text = 'Connect App to RCSL AI Nexus'
$connectButton.Location = New-Object Drawing.Point(27, 400)
$connectButton.Size = New-Object Drawing.Size(250, 38)
$form.Controls.Add($connectButton)

$openAiButton = New-Object Windows.Forms.Button
$openAiButton.Text = 'Switch App back to OpenAI'
$openAiButton.Location = New-Object Drawing.Point(287, 400)
$openAiButton.Size = New-Object Drawing.Size(220, 38)
$form.Controls.Add($openAiButton)

$doctorButton = New-Object Windows.Forms.Button
$doctorButton.Text = 'Open Doctor'
$doctorButton.Location = New-Object Drawing.Point(517, 400)
$doctorButton.Size = New-Object Drawing.Size(170, 38)
$form.Controls.Add($doctorButton)

$statusBox = New-Object Windows.Forms.TextBox
$statusBox.Location = New-Object Drawing.Point(27, 458)
$statusBox.Size = New-Object Drawing.Size(660, 132)
$statusBox.Multiline = $true
$statusBox.ReadOnly = $true
$statusBox.ScrollBars = 'Vertical'
$statusBox.BackColor = [Drawing.Color]::White
$form.Controls.Add($statusBox)

function Set-UiBusy {
    param([bool]$Busy)
    $connectButton.Enabled = -not $Busy
    $openAiButton.Enabled = -not $Busy
    $doctorButton.Enabled = -not $Busy
    $form.UseWaitCursor = $Busy
    [Windows.Forms.Application]::DoEvents()
}

function Write-UiStatus {
    param([string]$Message)
    $stamp = [DateTime]::Now.ToString('HH:mm:ss')
    $statusBox.AppendText("[$stamp] $Message`r`n")
}

function Refresh-UiStatus {
    try {
        $status = Get-CodexSwitcherStatus -ProjectPath $projectPathBox.Text.Trim()
        $installed = if ($status.AppInstalled) { "installed $($status.AppVersion)" } else { 'not installed' }
        $running = if ($status.AppRunning) { 'running' } else { 'stopped' }
        $modeLabel.Text = "User-level default: $($status.UserSelectionMode); App $installed; $running"
        foreach ($configurationIssue in @($status.ConfigurationIssues)) {
            Write-UiStatus "Configuration warning: $configurationIssue"
        }
        if (@($status.HigherPrecedenceProjectConfigs).Count -gt 0) {
            Write-UiStatus 'Warning: a project .codex/config.toml can override this user-level selection. Run Doctor for its path.'
        }
        if ($status.PersistedMachineKeyPresent) {
            Write-UiStatus 'Warning: a machine-level RCSL_API_KEY exists. This tool cannot remove it without elevation.'
        }
        elseif ($status.PersistedUserKeyPresent) {
            Write-UiStatus 'Notice: a legacy user-level RCSL_API_KEY exists. You can remove it when switching back.'
        }
    }
    catch {
        $modeLabel.Text = 'Current state: unavailable'
        Write-UiStatus $_.Exception.Message
    }
}

$operationScript = {
    param($ModulePath, $Action, $ApiKey, $BaseUrl, $Capability, $ValidateGateway, $RemovePersistedUserKey)
    Import-Module $ModulePath -Force
    if ($Action -eq 'connect') {
        return (Enable-RcslCodexApp -ApiKey $ApiKey -BaseUrl $BaseUrl -Capability $Capability -InstallIfMissing -ValidateGateway:$ValidateGateway)
    }
    return (Disable-RcslCodexApp -InstallIfMissing -RemovePersistedUserKey:$RemovePersistedUserKey)
}

$script:operation = $null
$operationTimer = New-Object Windows.Forms.Timer
$operationTimer.Interval = 200
$operationTimer.Add_Tick({
    if ($null -eq $script:operation -or -not $script:operation.AsyncResult.IsCompleted) {
        return
    }
    $operationTimer.Stop()
    $operation = $script:operation
    $script:operation = $null
    try {
        $outputs = @($operation.PowerShell.EndInvoke($operation.AsyncResult))
        $result = $outputs | Select-Object -Last 1
        if ($operation.Action -eq 'connect') {
            Write-UiStatus "Codex App configuration survived startup (PID $($result.ProcessId)); backup: $($result.BackupPath)"
            Write-UiStatus 'The full App agent loop is still unverified. Create a new task and request a real file operation.'
        }
        else {
            Write-UiStatus "Codex App started in OpenAI/default mode (PID $($result.ProcessId))."
            Write-UiStatus 'The inactive managed provider definition is intentionally preserved for older Nexus tasks.'
        }
    }
    catch {
        Write-UiStatus ("Failed: {0}" -f $_.Exception.Message)
        [Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Codex App operation failed', 'OK', 'Error') | Out-Null
    }
    finally {
        if ($null -ne $operation.ApiKey) {
            $operation.ApiKey.Dispose()
        }
        $operation.PowerShell.Dispose()
        $operation.Runspace.Dispose()
        Set-UiBusy -Busy $false
        Refresh-UiStatus
    }
})

function Start-UiOperation {
    param(
        [Parameter(Mandatory = $true)][ValidateSet('connect', 'restore')][string]$Action,
        [Security.SecureString]$ApiKey
    )
    if ($null -ne $script:operation) {
        throw 'Another operation is already running.'
    }
    $runspace = [RunspaceFactory]::CreateRunspace()
    $runspace.ApartmentState = [Threading.ApartmentState]::MTA
    $runspace.Open()
    $powerShell = [PowerShell]::Create()
    $powerShell.Runspace = $runspace
    [void]$powerShell.AddScript($operationScript).AddArgument((Join-Path $PSScriptRoot 'CodexAppSwitcher.Common.psm1')).AddArgument($Action).AddArgument($ApiKey).AddArgument($baseUrlBox.Text.Trim()).AddArgument($capabilityBox.Text.Trim()).AddArgument($validateCheck.Checked).AddArgument($removeLegacyCheck.Checked)
    $asyncResult = $powerShell.BeginInvoke()
    $script:operation = [pscustomobject]@{
        Action = $Action
        ApiKey = $ApiKey
        PowerShell = $powerShell
        Runspace = $runspace
        AsyncResult = $asyncResult
    }
    Set-UiBusy -Busy $true
    $operationTimer.Start()
}

$connectButton.Add_Click({
    if ([string]::IsNullOrWhiteSpace($apiKeyBox.Text)) {
        [Windows.Forms.MessageBox]::Show('Enter a Nexus API key.', 'API key required', 'OK', 'Warning') | Out-Null
        return
    }

    $secureKey = ConvertTo-SecureString -String $apiKeyBox.Text.Trim() -AsPlainText -Force
    $apiKeyBox.Clear()
    try {
        Write-UiStatus 'Preparing the Nexus connection. Codex App will be asked to close gracefully.'
        Start-UiOperation -Action 'connect' -ApiKey $secureKey
    }
    catch {
        $secureKey.Dispose()
        Write-UiStatus ("Failed: {0}" -f $_.Exception.Message)
        [Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Could not connect Codex App', 'OK', 'Error') | Out-Null
    }
})

$openAiButton.Add_Click({
    try {
        Write-UiStatus 'Restoring the pre-switch model/provider selection and restarting Codex App without the Nexus key.'
        Start-UiOperation -Action 'restore'
    }
    catch {
        Write-UiStatus ("Failed: {0}" -f $_.Exception.Message)
        [Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Could not restore Codex App', 'OK', 'Error') | Out-Null
    }
})

$doctorButton.Add_Click({
    try {
        $doctor = Join-Path $PSScriptRoot 'Test-CodexAppConnection.ps1'
        $hostPath = (Get-Command powershell.exe -ErrorAction Stop).Path
        $arguments = @(
            '-NoProfile', '-STA', '-NoExit', '-File', ('"{0}"' -f $doctor),
            '-BaseUrl', ('"{0}"' -f $baseUrlBox.Text.Trim()),
            '-Capability', ('"{0}"' -f $capabilityBox.Text.Trim()),
            '-ProjectPath', ('"{0}"' -f $projectPathBox.Text.Trim()),
            '-Online', '-Authenticated'
        )
        Start-Process -FilePath $hostPath -ArgumentList $arguments
    }
    catch {
        Write-UiStatus ("Could not open Doctor: {0}" -f $_.Exception.Message)
    }
})

$form.Add_Shown({
    Write-UiStatus 'No local or remote check has run yet.'
    Refresh-UiStatus
    $apiKeyBox.Focus()
})

$form.Add_FormClosing({
    param($sender, $eventArgs)
    if ($null -ne $script:operation) {
        $eventArgs.Cancel = $true
        [Windows.Forms.MessageBox]::Show('Wait for the current switch transaction to finish before closing this window.', 'Operation in progress', 'OK', 'Warning') | Out-Null
    }
})

[void]$form.ShowDialog()
