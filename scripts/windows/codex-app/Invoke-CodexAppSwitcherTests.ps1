<#
    Exercises the switcher's TOML handling against the shapes Codex App actually
    writes. Deliberately free of a test framework: the code under test is Windows
    PowerShell 5.1 with Set-StrictMode -Version Latest, and three of the faults
    this suite pins were visible only under that exact host, so the suite runs
    there with nothing to install first.

    None of these tests touch the App, the registry, the network, config.toml, or
    switcher state. They call the pure functions in module scope. Two of them
    write and delete a file of their own under the temp directory, because the
    defects they pin are encoding defects and there is no way to pin those
    without a file.

    Keep this file ASCII: Windows PowerShell reads a BOM-less script in the system
    codepage, so a literal non-ASCII character here would not survive the round
    trip. The one non-ASCII fixture is built from character codes instead.
#>
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$module = Import-Module (Join-Path $PSScriptRoot 'CodexAppSwitcher.Common.psm1') -Force -PassThru

$outcome = & $module {
    $script:passed = 0
    $script:failures = [Collections.Generic.List[string]]::new()

    function Test-Case {
        param(
            [Parameter(Mandatory = $true)][string]$Name,
            [Parameter(Mandatory = $true)][scriptblock]$Body
        )
        try {
            & $Body
            $script:passed++
        }
        catch {
            $script:failures.Add(("{0}`n      {1}" -f $Name, $_.Exception.Message))
        }
    }

    function Assert-Equal {
        param($Expected, $Actual, [string]$Because = '')
        if ($Expected -ne $Actual) {
            throw ("expected [{0}], got [{1}]. {2}" -f $Expected, $Actual, $Because)
        }
    }

    function Assert-True {
        param($Condition, [string]$Because = '')
        if (-not $Condition) {
            throw ("expected a true condition. {0}" -f $Because)
        }
    }

    function Assert-Throws {
        param(
            [Parameter(Mandatory = $true)][scriptblock]$Body,
            [Parameter(Mandatory = $true)][string]$MessagePattern
        )
        try {
            & $Body
        }
        catch {
            if ($_.Exception.Message -notmatch $MessagePattern) {
                throw ("threw, but not with /{0}/: {1}" -f $MessagePattern, $_.Exception.Message)
            }
            return
        }
        throw ("expected a throw matching /{0}/, but the call succeeded." -f $MessagePattern)
    }

    function New-Lines {
        # The unary comma matters: returned bare, the list arrives as an object[],
        # the callee rebuilds it to bind [List[string]], and every mutation the test
        # is checking for is made to a copy.
        param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Text)
        return ,(Split-TomlLines -Text $Text).Lines
    }

    # A config.toml in the shape Codex App writes one: blank lines between tables,
    # literal-quoted project paths carrying backslashes and spaces, basic-quoted
    # plugin ids carrying '@', and a quoted key inside a table that is not ours.
    $cjkSegment = -join ([char]0x8A9E, [char]0x8A00)
    $appWrittenConfig = @(
        'model = "gpt-5.6-terra"',
        'model_reasoning_effort = "high"',
        'notify = [ "C:\\Users\\test\\notify.exe", "turn-ended" ]',
        '',
        "[projects.'c:\users\test user\my project']",
        'trust_level = "trusted"',
        '',
        "[projects.'c:\dev\$cjkSegment']",
        'trust_level = "trusted"',
        '',
        '[tui.model_availability_nux]',
        '"gpt-5.6-sol" = 1',
        '',
        '[plugins."browser@openai-bundled"]',
        'enabled = true',
        '',
        '[mcp_servers.node_repl.env]',
        'CODEX_HOME = ' + "'C:\Users\test\.codex'"
    ) -join "`n"

    # -- table header parsing -------------------------------------------------

    Test-Case 'a bare table header parses' {
        $header = Get-TomlTableHeader -Line '[projects]'
        Assert-True ($null -ne $header)
        Assert-Equal 1 $header.Segments.Count
        Assert-Equal 'projects' $header.Segments[0]
        Assert-True (-not $header.IsArrayOfTables)
        Assert-True $header.Resolvable
    }

    Test-Case 'a dotted bare header parses into its segments' {
        $header = Get-TomlTableHeader -Line '[mcp_servers.node_repl.env]'
        Assert-Equal 3 $header.Segments.Count
        Assert-Equal 'env' $header.Segments[2]
    }

    Test-Case 'a literal-quoted segment keeps its backslashes and spaces' {
        $header = Get-TomlTableHeader -Line "[projects.'c:\users\test user\my project']"
        Assert-Equal 2 $header.Segments.Count
        Assert-Equal 'c:\users\test user\my project' $header.Segments[1]
    }

    Test-Case 'a literal-quoted segment keeps non-ASCII characters' {
        $header = Get-TomlTableHeader -Line ("[projects.'c:\dev\{0}']" -f $cjkSegment)
        Assert-Equal ('c:\dev\{0}' -f $cjkSegment) $header.Segments[1]
    }

    Test-Case 'a basic-quoted segment carrying @ parses' {
        $header = Get-TomlTableHeader -Line '[plugins."browser@openai-bundled"]'
        Assert-Equal 'browser@openai-bundled' $header.Segments[1]
    }

    Test-Case 'a trailing comment does not stop a header from parsing' {
        Assert-True (Test-TomlTableHeader -Line '[projects] # trusted set')
    }

    Test-Case 'an array-of-tables header is a header and is marked as one' {
        $header = Get-TomlTableHeader -Line '[[servers]]'
        Assert-True $header.IsArrayOfTables
        Assert-Equal 'servers' $header.Segments[0]
    }

    Test-Case 'a key line, a comment and an empty line are not headers' {
        Assert-True (-not (Test-TomlTableHeader -Line 'model = "code"'))
        Assert-True (-not (Test-TomlTableHeader -Line '# [projects]'))
        Assert-True (-not (Test-TomlTableHeader -Line ''))
    }

    Test-Case 'a basic-quoted segment with an escape is not resolvable' {
        $header = Get-TomlTableHeader -Line '[model_providers."a\\b"]'
        Assert-True (-not $header.Resolvable)
    }

    Test-Case 'the managed provider table is recognised bare and quoted' {
        Assert-True (Test-ManagedProviderHeader -Line '[model_providers.rcsl_nexus_switcher]')
        Assert-True (Test-ManagedProviderHeader -Line '["model_providers"."rcsl_nexus_switcher"]')
        Assert-True (-not (Test-ManagedProviderHeader -Line '[model_providers.other]'))
        Assert-True (-not (Test-ManagedProviderHeader -Line '[model_providers.rcsl_nexus_switcher.auth]'))
        Assert-True (Test-ManagedProviderAuthHeader -Line '[model_providers.rcsl_nexus_switcher.auth]')
    }

    # -- line splitting -------------------------------------------------------

    Test-Case 'CRLF text splits without leaving carriage returns behind' {
        $parts = Split-TomlLines -Text "a = 1`r`nb = 2`r`n"
        Assert-Equal 2 $parts.Lines.Count
        Assert-Equal 'b = 2' $parts.Lines[1]
        Assert-Equal "`r`n" $parts.Newline
        Assert-True $parts.HasTrailingNewline
    }

    Test-Case 'LF text splits and keeps LF as the joining newline' {
        $parts = Split-TomlLines -Text "a = 1`nb = 2`n"
        Assert-Equal 2 $parts.Lines.Count
        Assert-Equal "`n" $parts.Newline
    }

    Test-Case 'mixed line endings do not leave a stray newline inside a line' {
        $parts = Split-TomlLines -Text "model = `"a`"`r`nmodel_provider = `"b`"`n"
        Assert-Equal 2 $parts.Lines.Count
        Assert-Equal 'model_provider = "b"' $parts.Lines[1]
        Assert-Equal 1 (Find-TopLevelKeyIndices -Lines $parts.Lines -Key 'model_provider').Count
    }

    Test-Case 'text without a trailing newline keeps its last line' {
        $parts = Split-TomlLines -Text "a = 1`nb = 2"
        Assert-Equal 2 $parts.Lines.Count
        Assert-True (-not $parts.HasTrailingNewline)
    }

    Test-Case 'empty text yields an empty line list rather than one empty line' {
        $parts = Split-TomlLines -Text ''
        Assert-Equal 0 $parts.Lines.Count
    }

    # -- top-level key lookup -------------------------------------------------

    Test-Case 'an absent top-level key returns a countable empty result' {
        $lines = New-Lines -Text "approval_policy = `"on-request`"`n"
        $indices = Find-TopLevelKeyIndices -Lines $lines -Key 'model'
        Assert-Equal 0 $indices.Count
    }

    Test-Case 'a single top-level key returns a countable one-element result' {
        $lines = New-Lines -Text "model = `"code`"`n"
        $indices = Find-TopLevelKeyIndices -Lines $lines -Key 'model'
        Assert-Equal 1 $indices.Count
        Assert-Equal 0 $indices[0]
    }

    Test-Case 'a key below a quoted table header is not a top-level key' {
        $lines = New-Lines -Text $appWrittenConfig
        Assert-Equal 1 (Find-TopLevelKeyIndices -Lines $lines -Key 'model').Count
        Assert-Equal 0 (Find-TopLevelKeyIndices -Lines $lines -Key 'model_provider').Count
    }

    Test-Case 'a duplicated top-level key is refused' {
        $lines = New-Lines -Text "model = `"a`"`nmodel = `"b`"`n"
        Assert-Throws -MessagePattern 'more than one' -Body { Find-TopLevelKeyIndices -Lines $lines -Key 'model' }
    }

    Test-Case 'reading an absent key yields an empty value, not a throw' {
        $lines = New-Lines -Text $appWrittenConfig
        Assert-Equal '' (Get-TopLevelTomlValue -Lines $lines -Key 'model_provider')
        Assert-Equal 'gpt-5.6-terra' (Get-TopLevelTomlValue -Lines $lines -Key 'model')
        Assert-True (-not (Get-OriginalTopLevelKey -Lines $lines -Key 'model_provider').Present)
    }

    # -- the safety guard -----------------------------------------------------

    Test-Case 'a config Codex App itself wrote is accepted' {
        $lines = New-Lines -Text $appWrittenConfig
        Assert-SafeTomlForManagedEdit -Lines $lines
    }

    Test-Case 'an absent config, read as empty text, is accepted' {
        Assert-SafeTomlForManagedEdit -Lines (New-Lines -Text '')
    }

    Test-Case 'a multiline string is refused' {
        $lines = New-Lines -Text "instructions = `"`"`"`nhello`n`"`"`"`n"
        Assert-Throws -MessagePattern 'multiline string' -Body { Assert-SafeTomlForManagedEdit -Lines $lines }
    }

    Test-Case 'a quoted key in the top-level section is refused' {
        $lines = New-Lines -Text "`"model`" = `"code`"`n"
        Assert-Throws -MessagePattern 'quoted key in the top-level section' -Body { Assert-SafeTomlForManagedEdit -Lines $lines }
    }

    Test-Case 'a quoted key inside the managed provider table is refused' {
        $lines = New-Lines -Text "[model_providers.rcsl_nexus_switcher]`n`"base_url`" = `"https://x/v1`"`n"
        Assert-Throws -MessagePattern 'quoted key in \[model_providers' -Body { Assert-SafeTomlForManagedEdit -Lines $lines }
    }

    Test-Case 'a quoted key in someone else table is left alone' {
        $lines = New-Lines -Text "[tui.model_availability_nux]`n`"gpt-5.6-sol`" = 1`n"
        Assert-SafeTomlForManagedEdit -Lines $lines
    }

    Test-Case 'an inline model_providers table is refused' {
        $lines = New-Lines -Text "model_providers = { rcsl_nexus_switcher = { base_url = `"https://x/v1`" } }`n"
        Assert-Throws -MessagePattern 'inline or dotted key' -Body { Assert-SafeTomlForManagedEdit -Lines $lines }
    }

    Test-Case 'a dotted managed-provider key is refused' {
        $lines = New-Lines -Text "model_providers.rcsl_nexus_switcher.base_url = `"https://x/v1`"`n"
        Assert-Throws -MessagePattern 'inline or dotted key' -Body { Assert-SafeTomlForManagedEdit -Lines $lines }
    }

    Test-Case 'a nested table under the managed provider is refused' {
        $lines = New-Lines -Text "[model_providers.rcsl_nexus_switcher.http]`ntimeout = 30`n"
        Assert-Throws -MessagePattern 'nested table' -Body { Assert-SafeTomlForManagedEdit -Lines $lines }
    }

    Test-Case 'model_providers as an array of tables is refused' {
        $lines = New-Lines -Text "[[model_providers]]`nname = `"x`"`n"
        Assert-Throws -MessagePattern 'array of tables' -Body { Assert-SafeTomlForManagedEdit -Lines $lines }
    }

    Test-Case 'an unrelated array of tables is accepted' {
        $lines = New-Lines -Text "[[servers]]`nname = `"x`"`n"
        Assert-SafeTomlForManagedEdit -Lines $lines
    }

    Test-Case 'a multi-line array in the top-level section is refused' {
        $lines = New-Lines -Text "notify = [`n  `"a`",`n]`n"
        Assert-Throws -MessagePattern 'multi-line array' -Body { Assert-SafeTomlForManagedEdit -Lines $lines }
    }

    Test-Case 'a single-line array in the top-level section is accepted' {
        $lines = New-Lines -Text "notify = [ `"a`", `"b`" ]`n"
        Assert-SafeTomlForManagedEdit -Lines $lines
    }

    Test-Case 'an escaped table-key segment is refused rather than silently missed' {
        $lines = New-Lines -Text "[model_providers.`"rcsl\\u005fnexus`"]`nname = `"x`"`n"
        Assert-Throws -MessagePattern 'escaped table-key segment' -Body { Assert-SafeTomlForManagedEdit -Lines $lines }
    }

    # -- switching and restoring ----------------------------------------------

    function Switch-FixtureToRcsl {
        param(
            [Parameter(Mandatory = $true)][AllowEmptyString()][AllowEmptyCollection()][Collections.Generic.List[string]]$Lines,
            [string]$BaseUrl = 'https://llmapi.rcsl.online',
            [switch]$AllowExistingManaged
        )
        Set-TopLevelTomlKey -Lines $Lines -Key 'model_provider' -Line 'model_provider = "rcsl_nexus_switcher"'
        Set-TopLevelTomlKey -Lines $Lines -Key 'model' -Line 'model = "code"'
        Set-RcslProviderTable -Lines $Lines -BaseUrl $BaseUrl -AllowExistingManaged:$AllowExistingManaged
    }

    Test-Case 'switching an App-written config selects the managed provider and defines it once' {
        $lines = New-Lines -Text $appWrittenConfig
        Switch-FixtureToRcsl -Lines $lines
        Assert-Equal 'rcsl_nexus_switcher' (Get-TopLevelTomlValue -Lines $lines -Key 'model_provider')
        Assert-Equal 'code' (Get-TopLevelTomlValue -Lines $lines -Key 'model')
        $range = Find-ManagedProviderTableRange -Lines $lines
        Assert-True ($null -ne $range)
        Assert-True (-not $range.Duplicate)
        Assert-Equal 0 (Get-ManagedProviderIssues -Lines $lines).Count
    }

    Test-Case 'switching does not disturb the tables the App owns' {
        $lines = New-Lines -Text $appWrittenConfig
        Switch-FixtureToRcsl -Lines $lines
        $text = Join-TomlLines -Lines $lines -Newline "`n"
        foreach ($preserved in @(
                "[projects.'c:\users\test user\my project']",
                '[plugins."browser@openai-bundled"]',
                '"gpt-5.6-sol" = 1',
                'model_reasoning_effort = "high"'
            )) {
            Assert-True ($text.Contains($preserved)) -Because "lost: $preserved"
        }
    }

    Test-Case 'writing the managed table twice updates it in place instead of failing' {
        # Regression: the accumulator here was named $matches, which -match rebinds
        # to a Hashtable on its first success. This is the path Switch back to
        # OpenAI takes, after the operator App has already been closed.
        $lines = New-Lines -Text $appWrittenConfig
        Switch-FixtureToRcsl -Lines $lines
        $before = (Find-ManagedProviderTableRange -Lines $lines)
        Set-RcslProviderTable -Lines $lines -BaseUrl 'https://llmapi.rcsl.online' -AllowExistingManaged
        $after = Find-ManagedProviderTableRange -Lines $lines
        Assert-True (-not $after.Duplicate)
        Assert-Equal ($before.End - $before.Start) ($after.End - $after.Start)
        Assert-Equal 0 (Get-ManagedProviderIssues -Lines $lines).Count
    }

    Test-Case 'a changed base URL is rewritten rather than appended' {
        $lines = New-Lines -Text $appWrittenConfig
        Switch-FixtureToRcsl -Lines $lines
        Set-RcslProviderTable -Lines $lines -BaseUrl 'https://other.example.org' -AllowExistingManaged
        $range = Find-ManagedProviderTableRange -Lines $lines
        $baseUrls = @()
        for ($i = $range.Start + 1; $i -lt $range.End; $i++) {
            if ($lines[$i] -match '^\s*base_url\s*=\s*"([^"]+)"') { $baseUrls += $Matches[1] }
        }
        Assert-Equal 1 $baseUrls.Count
        Assert-Equal 'https://other.example.org/v1' $baseUrls[0]
    }

    Test-Case 'an existing managed table is not overwritten without proof of ownership' {
        $lines = New-Lines -Text "[model_providers.rcsl_nexus_switcher]`nname = `"RCSL AI Nexus`"`n"
        Assert-Throws -MessagePattern 'cannot prove it owns' -Body {
            Set-RcslProviderTable -Lines $lines -BaseUrl 'https://llmapi.rcsl.online'
        }
    }

    Test-Case 'a managed table carrying its own auth is refused' {
        $lines = New-Lines -Text "[model_providers.rcsl_nexus_switcher]`nname = `"x`"`n[model_providers.rcsl_nexus_switcher.auth]`nkind = `"x`"`n"
        Assert-Throws -MessagePattern 'auth\]' -Body {
            Set-RcslProviderTable -Lines $lines -BaseUrl 'https://llmapi.rcsl.online' -AllowExistingManaged
        }
    }

    Test-Case 'the managed table ends at the next table, including a quoted one' {
        $lines = New-Lines -Text ("[model_providers.rcsl_nexus_switcher]`nname = `"RCSL AI Nexus`"`n[projects.'c:\dev\x']`ntrust_level = `"trusted`"`n")
        $range = Find-ManagedProviderTableRange -Lines $lines
        Assert-Equal 0 $range.Start
        Assert-Equal 2 $range.End
    }

    Test-Case 'switching and restoring returns the document to what it was' {
        $lines = New-Lines -Text $appWrittenConfig
        $originalModel = Get-OriginalTopLevelKey -Lines $lines -Key 'model'
        $originalProvider = Get-OriginalTopLevelKey -Lines $lines -Key 'model_provider'

        Switch-FixtureToRcsl -Lines $lines
        Set-RcslProviderTable -Lines $lines -BaseUrl 'https://llmapi.rcsl.online' -AllowExistingManaged
        Restore-TopLevelTomlKey -Lines $lines -Key 'model' -Original $originalModel
        Restore-TopLevelTomlKey -Lines $lines -Key 'model_provider' -Original $originalProvider

        Assert-Equal 'gpt-5.6-terra' (Get-TopLevelTomlValue -Lines $lines -Key 'model')
        Assert-Equal '' (Get-TopLevelTomlValue -Lines $lines -Key 'model_provider')
        # The inactive provider definition is kept on purpose: removing it breaks a
        # conversation created against it.
        Assert-True ($null -ne (Find-ManagedProviderTableRange -Lines $lines))
    }

    Test-Case 'restoring an original selection that existed puts the exact line back' {
        $lines = New-Lines -Text "model = `"gpt-5`"`nmodel_provider = `"openai`"`n"
        $originalProvider = Get-OriginalTopLevelKey -Lines $lines -Key 'model_provider'
        Switch-FixtureToRcsl -Lines $lines
        Assert-Equal 'rcsl_nexus_switcher' (Get-TopLevelTomlValue -Lines $lines -Key 'model_provider')
        Restore-TopLevelTomlKey -Lines $lines -Key 'model_provider' -Original $originalProvider
        Assert-Equal 'openai' (Get-TopLevelTomlValue -Lines $lines -Key 'model_provider')
    }

    # -- provider validation and drift ----------------------------------------

    Test-Case 'a provider table missing wire_api is reported' {
        $lines = New-Lines -Text "[model_providers.rcsl_nexus_switcher]`nname = `"RCSL AI Nexus`"`nenv_key = `"RCSL_API_KEY`"`nbase_url = `"https://x/v1`"`n"
        $issues = Get-ManagedProviderIssues -Lines $lines
        Assert-Equal 1 $issues.Count
        Assert-True ($issues[0] -match 'wire_api')
    }

    Test-Case 'issues enumerate as strings for a caller that iterates them directly' {
        # Pins the caller contract of a unary-comma return: iterate it, do not wrap
        # it in @(), or the list becomes the one element.
        $lines = New-Lines -Text "[model_providers.rcsl_nexus_switcher]`nname = `"RCSL AI Nexus`"`nenv_key = `"RCSL_API_KEY`"`nbase_url = `"https://x/v1`"`n"
        $collected = [Collections.Generic.List[string]]::new()
        foreach ($issue in (Get-ManagedProviderIssues -Lines $lines)) {
            $collected.Add([string]$issue)
        }
        Assert-Equal 1 $collected.Count
        Assert-True ($collected[0] -match 'wire_api')

        $clean = New-Lines -Text "[model_providers.rcsl_nexus_switcher]`nname = `"RCSL AI Nexus`"`nenv_key = `"RCSL_API_KEY`"`nwire_api = `"responses`"`nbase_url = `"https://x/v1`"`n"
        $none = 0
        foreach ($issue in (Get-ManagedProviderIssues -Lines $clean)) { $none++ }
        Assert-Equal 0 $none
    }

    Test-Case 'a non-HTTPS base URL is reported' {
        $lines = New-Lines -Text "[model_providers.rcsl_nexus_switcher]`nname = `"RCSL AI Nexus`"`nenv_key = `"RCSL_API_KEY`"`nwire_api = `"responses`"`nbase_url = `"http://x/v1`"`n"
        $issues = Get-ManagedProviderIssues -Lines $lines
        Assert-Equal 1 $issues.Count
        Assert-True ($issues[0] -match 'base_url')
    }

    Test-Case 'the managed projection hash ignores unrelated edits and catches ours' {
        $lines = New-Lines -Text $appWrittenConfig
        Switch-FixtureToRcsl -Lines $lines
        $baseline = Get-ManagedProjectionSha256 -Lines $lines

        $lines.Add('')
        $lines.Add('[experimental]')
        $lines.Add('flag = true')
        Assert-Equal $baseline (Get-ManagedProjectionSha256 -Lines $lines) -Because 'an unrelated table moved the hash'

        Set-TopLevelTomlKey -Lines $lines -Key 'model' -Line 'model = "chat"'
        Assert-True ($baseline -ne (Get-ManagedProjectionSha256 -Lines $lines)) -Because 'a changed selection did not move the hash'
    }

    # -- gateway URL normalisation --------------------------------------------

    Test-Case 'a plain HTTPS origin normalises to itself' {
        Assert-Equal 'https://llmapi.rcsl.online' (Get-NormalizedGatewayBaseUrl -BaseUrl 'https://llmapi.rcsl.online/')
    }

    Test-Case 'a URL carrying a path, query, credentials or plain HTTP is refused' {
        foreach ($rejected in @(
                'https://llmapi.rcsl.online/v1',
                'https://llmapi.rcsl.online/?k=1',
                'https://user:pass@llmapi.rcsl.online',
                'http://llmapi.rcsl.online'
            )) {
            Assert-Throws -MessagePattern 'HTTPS origin' -Body { Get-NormalizedGatewayBaseUrl -BaseUrl $rejected }
        }
    }

    Test-Case 'a TOML string value is escaped before it is written' {
        Assert-Equal 'c:\\dev\\x' (ConvertTo-TomlEscapedString -Value 'c:\dev\x')
        Assert-Equal '\"quoted\"' (ConvertTo-TomlEscapedString -Value '"quoted"')
    }

    # -- reading a model catalogue ---------------------------------------------

    Test-Case 'the capability list is read out of a well-formed catalogue' {
        $body = '{"object":"list","data":[{"id":"code"},{"id":"chat"}]}' | ConvertFrom-Json
        $ids = Get-ModelCatalogueIds -Response $body
        Assert-Equal 2 $ids.Count
        Assert-True ($ids -contains 'code')
    }

    Test-Case 'a catalogue with no data key yields nothing rather than throwing' {
        # Dotting into a missing property is a terminating error under
        # Set-StrictMode, so a proxy or error page answering 200 used to abort the
        # switch with a message about a missing property.
        foreach ($body in @(
                ('{"object":"list"}' | ConvertFrom-Json),
                ('{"data":null}' | ConvertFrom-Json),
                ('"a string"' | ConvertFrom-Json)
            )) {
            $ids = Get-ModelCatalogueIds -Response $body
            Assert-Equal 0 $ids.Count
        }
        Assert-Equal 0 (Get-ModelCatalogueIds -Response $null).Count
    }

    Test-Case 'catalogue entries without an id are skipped, not rendered empty' {
        $body = '{"data":[{"id":"code"},{"name":"no id here"}]}' | ConvertFrom-Json
        $ids = Get-ModelCatalogueIds -Response $body
        Assert-Equal 1 $ids.Count
        Assert-Equal 'code' $ids[0]
    }

    # -- refusing before the App is closed -------------------------------------

    Test-Case 'a duplicate top-level key is refused by the preflight, not by the write' {
        $lines = New-Lines -Text "model = `"a`"`nmodel = `"b`"`n"
        # The safety guard alone lets this through; the rehearsal is what catches
        # it, and the rehearsal is what runs before the operator's App is closed.
        Assert-SafeTomlForManagedEdit -Lines $lines
        Assert-Throws -MessagePattern "more than one top-level 'model'" -Body {
            Assert-DocumentCanBeSwitched -Lines $lines -BaseUrl 'https://llmapi.rcsl.online' -Capability 'code'
        }
    }

    Test-Case 'an incompatible provider field is refused by the preflight' {
        $lines = New-Lines -Text "[model_providers.rcsl_nexus_switcher]`nname = `"RCSL AI Nexus`"`nexperimental_bearer_token = `"x`"`n"
        Assert-SafeTomlForManagedEdit -Lines $lines
        Assert-Throws -MessagePattern 'experimental_bearer_token' -Body {
            Assert-DocumentCanBeSwitched -Lines $lines -BaseUrl 'https://llmapi.rcsl.online' -Capability 'code' -AllowExistingManaged
        }
    }

    Test-Case 'the preflight rehearses on a copy and leaves the document alone' {
        $lines = New-Lines -Text $appWrittenConfig
        $before = Join-TomlLines -Lines $lines -Newline "`n"
        Assert-DocumentCanBeSwitched -Lines $lines -BaseUrl 'https://llmapi.rcsl.online' -Capability 'code'
        Assert-Equal $before (Join-TomlLines -Lines $lines -Newline "`n") -Because 'the rehearsal mutated the caller''s lines'
        Assert-True ($null -eq (Find-ManagedProviderTableRange -Lines $lines))
    }

    Test-Case 'a document the switcher can own passes the preflight' {
        Assert-DocumentCanBeSwitched -Lines (New-Lines -Text $appWrittenConfig) `
            -BaseUrl 'https://llmapi.rcsl.online' -Capability 'code'
    }

    Test-Case 'the restore preflight refuses a duplicate key before the App is closed' {
        $state = [pscustomobject]@{
            ProviderId = 'rcsl_nexus_switcher'
            GatewayBaseUrl = 'https://llmapi.rcsl.online'
            OriginalModel = [pscustomobject]@{ Present = $true; Line = 'model = "gpt-5"' }
            OriginalModelProvider = [pscustomobject]@{ Present = $false; Line = '' }
        }
        $lines = New-Lines -Text "model = `"a`"`nmodel = `"b`"`n"
        Assert-Throws -MessagePattern "more than one top-level 'model'" -Body {
            Assert-DocumentCanBeRestored -Lines $lines -State $state
        }
    }

    Test-Case 'restoring does not resurrect a provider table the operator deleted' {
        # The GUI reports the inactive definition as "preserved". Adding it back
        # when it is absent would make that message describe a resurrection.
        $state = [pscustomobject]@{
            ProviderId = 'rcsl_nexus_switcher'
            GatewayBaseUrl = 'https://llmapi.rcsl.online'
            OriginalModel = [pscustomobject]@{ Present = $true; Line = 'model = "gpt-5"' }
            OriginalModelProvider = [pscustomobject]@{ Present = $false; Line = '' }
        }
        $absent = New-Lines -Text "model = `"code`"`nmodel_provider = `"rcsl_nexus_switcher`"`n"
        Assert-True ($null -eq (Find-ManagedProviderTableRange -Lines $absent))
        Assert-True (-not (Test-ShouldRefreshManagedProvider -Lines $absent -State $state)) -Because 'an absent table would be written back'
        Assert-DocumentCanBeRestored -Lines $absent -State $state
        Assert-True ($null -eq (Find-ManagedProviderTableRange -Lines $absent)) -Because 'the table came back'

        $present = New-Lines -Text "model = `"code`"`nmodel_provider = `"rcsl_nexus_switcher`"`n`n[model_providers.rcsl_nexus_switcher]`nname = `"RCSL AI Nexus`"`n"
        Assert-True (Test-ShouldRefreshManagedProvider -Lines $present -State $state) -Because 'a present table would not be refreshed'

        Assert-True (-not (Test-ShouldRefreshManagedProvider -Lines $present -State $null)) -Because 'no state should mean no write'
    }

    # -- encodings that only bite on a non-UTF-8 locale ------------------------

    Test-Case 'switcher state survives a non-ASCII path through the reader it uses' {
        # Get-Content -Raw decodes a BOM-less file in the system codepage, which
        # mangles a ConfigPath containing non-ASCII and then blocks restoration on
        # a path mismatch. Read-Utf8Text is what Get-SwitcherState uses instead.
        $nonAscii = -join ([char]0x8A9E, [char]0x8A00)
        $payload = [pscustomobject]@{
            SchemaVersion = 2
            ConfigPath = "C:\Users\$nonAscii\.codex\config.toml"
            Mode = 'rcsl'
        }
        $file = Join-Path ([IO.Path]::GetTempPath()) ("switcher-state-test-{0}.json" -f [Guid]::NewGuid().ToString('N'))
        try {
            Write-Utf8TextAtomic -Path $file -Text (($payload | ConvertTo-Json -Depth 8) + "`n")
            $roundTripped = (Read-Utf8Text -Path $file | ConvertFrom-Json)
            Assert-Equal $payload.ConfigPath $roundTripped.ConfigPath
        }
        finally {
            if (Test-Path -LiteralPath $file) { Remove-Item -LiteralPath $file -Force }
        }
    }

    Test-Case 'the recorded config hash is comparable with the backup file on disk' {
        # The doctor compares ConfigSha256Before, taken over the text, against
        # Get-FileHash of the backup. That only means anything if the two agree.
        $text = "model = `"code`"`n# " + (-join ([char]0x8A9E, [char]0x8A00)) + "`n"
        $file = Join-Path ([IO.Path]::GetTempPath()) ("switcher-hash-test-{0}.toml" -f [Guid]::NewGuid().ToString('N'))
        try {
            Write-Utf8TextAtomic -Path $file -Text $text
            $fromText = Get-TextSha256 -Text $text
            $fromFile = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()
            Assert-Equal $fromText $fromFile
        }
        finally {
            if (Test-Path -LiteralPath $file) { Remove-Item -LiteralPath $file -Force }
        }
    }

    # -- recovery state, which fails closed or does not fail at all -----------

    function New-State {
        # A complete schema-2 state, so that a case removing one property is
        # testing that property and not the shape of the fixture.
        param([hashtable]$Override = @{})
        $state = [pscustomobject]@{
            SchemaVersion = 2
            Mode = 'rcsl'
            ConfigPath = 'C:\Users\op\.codex\config.toml'
            BackupPath = 'C:\Users\op\AppData\Local\RCSL\backups\config.toml.before-rcsl'
            ConfigSha256Before = ('0' * 64)
            OriginalModel = 'gpt-5.6-terra'
            OriginalModelProvider = $null
            ProviderId = 'rcsl_nexus_switcher'
            GatewayBaseUrl = 'https://llmapi.rcsl.online'
            Capability = 'code'
            AppVersion = '26.825.4187.0'
            SwitchedAtUtc = '2026-08-29T15:08:02.0000000Z'
        }
        foreach ($key in $Override.Keys) {
            $state | Add-Member -MemberType NoteProperty -Name $key -Value $Override[$key] -Force
        }
        return $state
    }

    Test-Case 'every mode the switcher writes is accepted' {
        foreach ($mode in @('preparing-rcsl', 'rcsl', 'openai')) {
            $state = New-State @{ Mode = $mode }
            Assert-SwitcherStateUsable -State $state -ConfigPath $state.ConfigPath
        }
    }

    Test-Case 'an unknown mode is refused rather than read as inactive' {
        # This is the fail-closed property section 6 of the runbook claims. The
        # check used to ask only "is the mode one of the two active ones", so a
        # truncated or hand-edited state answered "no" and the enable path then
        # overwrote the recovery metadata that was the way back.
        $state = New-State @{ Mode = 'corrupt' }
        Assert-Throws -MessagePattern "unknown mode 'corrupt'" -Body {
            Assert-SwitcherStateUsable -State $state -ConfigPath $state.ConfigPath
        }
    }

    Test-Case 'an empty mode is refused, not treated as absent state' {
        $state = New-State @{ Mode = '' }
        Assert-Throws -MessagePattern 'unknown mode' -Body {
            Assert-SwitcherStateUsable -State $state -ConfigPath $state.ConfigPath
        }
    }

    Test-Case 'a state missing any property the switcher relies on is refused' {
        # Named individually because each one is a different way back that would
        # otherwise be read as $null under Set-StrictMode only at the point of
        # use, which on this path is after the App has been closed.
        foreach ($name in @('Mode', 'ConfigPath', 'BackupPath', 'OriginalModel', 'OriginalModelProvider', 'ProviderId', 'Capability')) {
            $state = New-State
            $state.PSObject.Properties.Remove($name)
            Assert-Throws -MessagePattern ("missing: .*{0}" -f $name) -Body {
                Assert-SwitcherStateUsable -State $state -ConfigPath 'C:\Users\op\.codex\config.toml'
            }
        }
    }

    Test-Case 'a null OriginalModelProvider is a value, not a missing property' {
        # The common case: the operator had no model_provider line at all, and
        # restoration has to put that absence back. A presence check that
        # rejected $null would refuse every first switch.
        $state = New-State @{ OriginalModelProvider = $null }
        Assert-SwitcherStateUsable -State $state -ConfigPath $state.ConfigPath
    }

    Test-Case 'a null OriginalModelProvider survives the round trip the switcher makes' {
        # The case above builds the object in memory, and the input the checks
        # actually see is always ConvertTo-Json -> file -> ConvertFrom-Json. That
        # matters more now that a missing property fails closed on both paths: if
        # the round trip ever dropped a null-valued key, every operator whose
        # config.toml had no model_provider line -- the common first switch --
        # would be locked out of switching and of restoring, with this suite
        # green. Save-SwitcherState is deliberately not called, because the suite
        # promises to touch no recovery state; these are the two functions it
        # would use, pointed at a file of the test's own.
        $state = New-State @{ OriginalModelProvider = $null; OriginalModel = $null }
        $file = Join-Path ([IO.Path]::GetTempPath()) ("switcher-roundtrip-{0}.json" -f [Guid]::NewGuid().ToString('N'))
        try {
            Write-Utf8TextAtomic -Path $file -Text (($state | ConvertTo-Json -Depth 8) + "`n")
            $reloaded = (Read-Utf8Text -Path $file | ConvertFrom-Json)
            Assert-True ($null -ne $reloaded.PSObject.Properties['OriginalModelProvider']) -Because 'the key did not survive serialization'
            Assert-True ($null -eq $reloaded.OriginalModelProvider) -Because 'a null came back as something else'
            Assert-SwitcherStateUsable -State $reloaded -ConfigPath $reloaded.ConfigPath
            Assert-SwitcherStateUsable -State $reloaded -ConfigPath $reloaded.ConfigPath -ForRestore
        }
        finally {
            if (Test-Path -LiteralPath $file) { Remove-Item -LiteralPath $file -Force }
        }
    }

    Test-Case 'an unsupported schema is still refused before anything else' {
        $state = New-State @{ SchemaVersion = 1 }
        Assert-Throws -MessagePattern 'supported schema version' -Body {
            Assert-SwitcherStateUsable -State $state -ConfigPath $state.ConfigPath
        }
    }

    Test-Case 'restoring refuses a state belonging to another CODEX_HOME in any mode' {
        # -ForRestore is the stricter rule. An openai-mode state for another
        # profile is harmless to the enable path and is exactly what restoration
        # must not write back, and this used to be checked only after the App
        # had been closed.
        foreach ($mode in @('preparing-rcsl', 'rcsl', 'openai')) {
            $state = New-State @{ Mode = $mode; ConfigPath = 'C:\old\.codex\config.toml' }
            Assert-Throws -MessagePattern 'recovery state belongs to' -Body {
                Assert-SwitcherStateUsable -State $state -ConfigPath 'C:\Users\op\.codex\config.toml' -ForRestore
            }
        }
    }

    Test-Case 'switching refuses only an active session belonging to another CODEX_HOME' {
        $active = New-State @{ Mode = 'rcsl'; ConfigPath = 'C:\old\.codex\config.toml' }
        Assert-Throws -MessagePattern 'active RCSL session' -Body {
            Assert-SwitcherStateUsable -State $active -ConfigPath 'C:\Users\op\.codex\config.toml'
        }
        $settled = New-State @{ Mode = 'openai'; ConfigPath = 'C:\old\.codex\config.toml' }
        Assert-SwitcherStateUsable -State $settled -ConfigPath 'C:\Users\op\.codex\config.toml'
    }

    Test-Case 'no state is not a refusal' {
        Assert-SwitcherStateUsable -State $null -ConfigPath 'C:\Users\op\.codex\config.toml'
        Assert-SwitcherStateUsable -State $null -ConfigPath 'C:\Users\op\.codex\config.toml' -ForRestore
    }

    # -- invariants pinned over the source ------------------------------------
    #
    # These three are properties of the call sites rather than of any function, so
    # a test that exercises a helper cannot hold them: the orchestration they
    # belong to needs a real App to run. They follow the precedent already set in
    # backend/tests/unit/test_refusal_identity_and_permissions.py, which checks a
    # rule over the source for the same reason.

    $modulePath = Join-Path $PSScriptRoot 'CodexAppSwitcher.Common.psm1'

    function Get-CommandOrder {
        param(
            [Parameter(Mandatory = $true)][string]$Path,
            [Parameter(Mandatory = $true)][string]$FunctionName
        )
        $errors = $null
        $ast = [System.Management.Automation.Language.Parser]::ParseFile($Path, [ref]$null, [ref]$errors)
        if ($errors.Count -gt 0) { throw "the module does not parse: $($errors[0].Message)" }
        $function = $ast.Find({
                param($node)
                $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $FunctionName
            }, $true)
        if ($null -eq $function) { throw "no function named $FunctionName" }
        $names = [Collections.Generic.List[string]]::new()
        foreach ($command in $function.FindAll({
                    param($node) $node -is [System.Management.Automation.Language.CommandAst]
                }, $true)) {
            $name = $command.GetCommandName()
            if (-not [string]::IsNullOrEmpty($name)) { $names.Add($name) }
        }
        return ,$names
    }

    Test-Case 'the module parses and the source invariants have something to check' {
        Assert-True (Test-Path -LiteralPath $modulePath) -Because "module not found at $modulePath"
        Assert-True ((Get-CommandOrder -Path $modulePath -FunctionName 'Invoke-EnableRcslCodexAppCore').Count -gt 0)
    }

    Test-Case 'the enable path validates the document before it closes the App' {
        $order = Get-CommandOrder -Path $modulePath -FunctionName 'Invoke-EnableRcslCodexAppCore'
        $validate = $order.IndexOf('Assert-DocumentCanBeSwitched')
        $close = $order.IndexOf('Stop-CodexAppGracefully')
        Assert-True ($validate -ge 0) -Because 'the enable path no longer rehearses the edit'
        Assert-True ($close -ge 0) -Because 'the enable path no longer closes the App'
        Assert-True ($validate -lt $close) -Because 'a refusal now costs the operator a closed App'
    }

    Test-Case 'the restore path validates the document before it closes the App' {
        $order = Get-CommandOrder -Path $modulePath -FunctionName 'Invoke-DisableRcslCodexAppCore'
        $validate = $order.IndexOf('Assert-DocumentCanBeRestored')
        $close = $order.IndexOf('Stop-CodexAppGracefully')
        Assert-True ($validate -ge 0) -Because 'the restore path no longer rehearses the edit'
        Assert-True ($close -ge 0) -Because 'the restore path no longer closes the App'
        Assert-True ($validate -lt $close) -Because 'a refusal now costs the operator a closed App'
    }

    Test-Case 'the restore path validates the state before it closes the App' {
        # Separate from the document check above: the state is the other half of
        # what restoration reads, and the path check on it lived inline after the
        # close until a review reproduced a state for another CODEX_HOME passing
        # preflight. The authoritative recheck after the close stays.
        $order = Get-CommandOrder -Path $modulePath -FunctionName 'Invoke-DisableRcslCodexAppCore'
        $close = $order.IndexOf('Stop-CodexAppGracefully')
        $first = $order.IndexOf('Assert-SwitcherStateUsable')
        $last = $order.LastIndexOf('Assert-SwitcherStateUsable')
        Assert-True ($first -ge 0) -Because 'the restore path no longer validates the state at all'
        Assert-True ($close -ge 0) -Because 'the restore path no longer closes the App'
        Assert-True ($first -lt $close) -Because 'a state refusal again costs the operator a closed App'
        Assert-True ($last -gt $close) -Because 'the authoritative recheck after the close was dropped'
    }

    Test-Case 'nothing in the module reads a file with Get-Content' {
        # Get-Content decodes a BOM-less file in the system codepage on Windows
        # PowerShell 5.1. Read-Utf8Text exists so that no reader here has to
        # remember that, and Get-SwitcherState is the one that once forgot.
        $errors = $null
        $ast = [System.Management.Automation.Language.Parser]::ParseFile($modulePath, [ref]$null, [ref]$errors)
        $offenders = [Collections.Generic.List[string]]::new()
        foreach ($command in $ast.FindAll({
                    param($node) $node -is [System.Management.Automation.Language.CommandAst]
                }, $true)) {
            if ($command.GetCommandName() -in @('Get-Content', 'gc', 'cat', 'type')) {
                $offenders.Add("line $($command.Extent.StartLineNumber): $($command.Extent.Text)")
            }
        }
        Assert-Equal 0 $offenders.Count -Because ("use Read-Utf8Text instead: " + ($offenders -join '; '))
    }

    return [pscustomobject]@{
        Passed = $script:passed
        Failures = @($script:failures)
    }
}

$failed = @($outcome.Failures).Count
foreach ($failure in @($outcome.Failures)) {
    Write-Host ("  FAIL  {0}" -f $failure) -ForegroundColor Red
}
Write-Host ''
Write-Host ("{0} passed, {1} failed" -f $outcome.Passed, $failed)

if ($failed -gt 0) {
    exit 1
}
