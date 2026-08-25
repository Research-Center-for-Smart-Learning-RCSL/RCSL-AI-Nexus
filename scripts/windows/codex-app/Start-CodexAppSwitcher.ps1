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
$form.ClientSize = New-Object Drawing.Size(720, 560)
$form.MinimumSize = New-Object Drawing.Size(736, 599)
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

$apiKeyLabel = New-Object Windows.Forms.Label
$apiKeyLabel.Text = 'Nexus API key'
$apiKeyLabel.Location = New-Object Drawing.Point(27, 221)
$apiKeyLabel.AutoSize = $true
$form.Controls.Add($apiKeyLabel)

$apiKeyBox = New-Object Windows.Forms.TextBox
$apiKeyBox.Location = New-Object Drawing.Point(190, 217)
$apiKeyBox.Size = New-Object Drawing.Size(497, 25)
$apiKeyBox.UseSystemPasswordChar = $true
$form.Controls.Add($apiKeyBox)

$keyNote = New-Object Windows.Forms.Label
$keyNote.Text = 'The key is not persisted. It is validated and passed only to the newly started App process.'
$keyNote.ForeColor = [Drawing.Color]::DimGray
$keyNote.Location = New-Object Drawing.Point(190, 246)
$keyNote.Size = New-Object Drawing.Size(497, 35)
$form.Controls.Add($keyNote)

$validateCheck = New-Object Windows.Forms.CheckBox
$validateCheck.Text = 'Validate GET /v1/models before changing the App'
$validateCheck.Checked = $true
$validateCheck.Location = New-Object Drawing.Point(190, 278)
$validateCheck.Size = New-Object Drawing.Size(420, 25)
$form.Controls.Add($validateCheck)

$removeLegacyCheck = New-Object Windows.Forms.CheckBox
$removeLegacyCheck.Text = 'When switching back, remove a legacy user-level RCSL_API_KEY created with setx'
$removeLegacyCheck.Checked = $false
$removeLegacyCheck.Location = New-Object Drawing.Point(190, 306)
$removeLegacyCheck.Size = New-Object Drawing.Size(497, 40)
$form.Controls.Add($removeLegacyCheck)

$connectButton = New-Object Windows.Forms.Button
$connectButton.Text = 'Connect App to RCSL AI Nexus'
$connectButton.Location = New-Object Drawing.Point(27, 360)
$connectButton.Size = New-Object Drawing.Size(250, 38)
$form.Controls.Add($connectButton)

$openAiButton = New-Object Windows.Forms.Button
$openAiButton.Text = 'Switch App back to OpenAI'
$openAiButton.Location = New-Object Drawing.Point(287, 360)
$openAiButton.Size = New-Object Drawing.Size(220, 38)
$form.Controls.Add($openAiButton)

$doctorButton = New-Object Windows.Forms.Button
$doctorButton.Text = 'Open Doctor'
$doctorButton.Location = New-Object Drawing.Point(517, 360)
$doctorButton.Size = New-Object Drawing.Size(170, 38)
$form.Controls.Add($doctorButton)

$statusBox = New-Object Windows.Forms.TextBox
$statusBox.Location = New-Object Drawing.Point(27, 418)
$statusBox.Size = New-Object Drawing.Size(660, 112)
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
        $status = Get-CodexSwitcherStatus
        $installed = if ($status.AppInstalled) { "installed $($status.AppVersion)" } else { 'not installed' }
        $running = if ($status.AppRunning) { 'running' } else { 'stopped' }
        $modeLabel.Text = "Current state: $($status.EffectiveMode); App $installed; $running"
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

$connectButton.Add_Click({
    if ([string]::IsNullOrWhiteSpace($apiKeyBox.Text)) {
        [Windows.Forms.MessageBox]::Show('Enter a Nexus API key.', 'API key required', 'OK', 'Warning') | Out-Null
        return
    }

    $secureKey = ConvertTo-SecureString -String $apiKeyBox.Text.Trim() -AsPlainText -Force
    $apiKeyBox.Clear()
    Set-UiBusy -Busy $true
    try {
        Write-UiStatus 'Preparing the Nexus connection. Codex App will be asked to close gracefully.'
        $result = Enable-RcslCodexApp `
            -ApiKey $secureKey `
            -BaseUrl $baseUrlBox.Text.Trim() `
            -Capability $capabilityBox.Text.Trim() `
            -InstallIfMissing `
            -ValidateGateway:$validateCheck.Checked
        Write-UiStatus "Codex App started in Nexus mode (PID $($result.ProcessId)); backup: $($result.BackupPath)"
        Write-UiStatus 'Create a new App task before testing. Existing tasks retain the provider they were created with.'
    }
    catch {
        Write-UiStatus ("Failed: {0}" -f $_.Exception.Message)
        [Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Could not connect Codex App', 'OK', 'Error') | Out-Null
    }
    finally {
        $secureKey.Dispose()
        Set-UiBusy -Busy $false
        Refresh-UiStatus
    }
})

$openAiButton.Add_Click({
    Set-UiBusy -Busy $true
    try {
        Write-UiStatus 'Restoring the pre-switch model/provider selection and restarting Codex App without the Nexus key.'
        $result = Disable-RcslCodexApp `
            -InstallIfMissing `
            -RemovePersistedUserKey:$removeLegacyCheck.Checked
        Write-UiStatus "Codex App started in OpenAI/default mode (PID $($result.ProcessId))."
        Write-UiStatus 'The inactive rcsl provider definition is intentionally preserved for older Nexus tasks.'
    }
    catch {
        Write-UiStatus ("Failed: {0}" -f $_.Exception.Message)
        [Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Could not restore Codex App', 'OK', 'Error') | Out-Null
    }
    finally {
        Set-UiBusy -Busy $false
        Refresh-UiStatus
    }
})

$doctorButton.Add_Click({
    try {
        $doctor = Join-Path $PSScriptRoot 'Test-CodexAppConnection.ps1'
        $hostPath = (Get-Command powershell.exe -ErrorAction Stop).Path
        Start-Process -FilePath $hostPath -ArgumentList @('-NoProfile', '-NoExit', '-File', ('"{0}"' -f $doctor), '-Online', '-Authenticated')
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

[void]$form.ShowDialog()
