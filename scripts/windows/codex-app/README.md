# Windows Codex App switcher

This directory contains Windows-only operator tools for switching the local
Codex desktop app between the built-in OpenAI provider and RCSL AI Nexus.

The tools are deliberately App-first. The bundled `codex.exe` is used only as
an installation discovery fallback; these scripts do not install the npm Codex
CLI and do not use CLI profiles as a substitute for changing the desktop app.
OpenAI documents that the native Windows App and native CLI share the same
Codex home, so the selected provider is also visible to a later native CLI
process. The switcher relies on the directly launched App passing its
process-scoped key to the internal app-server; that inheritance is a project
hypothesis, not a documented compatibility guarantee. A separately launched
CLI needs its own process-scoped key or an OpenAI restoration first.

## Files

- `Start-CodexAppSwitcher.ps1` — Windows Forms UI with a masked API-key field,
  Connect and Restore actions, optional gateway validation, and automatic
  Microsoft Store installation through `winget` when the App is absent.
- `Test-CodexAppConnection.ps1` — read-only doctor for installation, process,
  configuration, recovery state, persistent-key, DNS, TLS, health, and
  authenticated model-catalogue checks. Its API-key prompt is a masked Windows
  dialog, not console or command-line input.
- `CodexAppSwitcher.Common.psm1` — shared transactional configuration, App
  discovery, graceful shutdown, launch, backup, and gateway functions.
- `Invoke-CodexAppSwitcherTests.ps1` — the configuration-handling suite, run by
  the `windows-client-tools` CI job. It touches no App, network, registry,
  `config.toml`, or recovery state.

## Launch

These files sit together, so every command below is run from the directory
holding this README. That is the directory the management UI's step 2 extracts
to, `%LOCALAPPDATA%\RCSL-AI-Nexus\client-tools`, or `scripts\windows\codex-app`
in a checkout. The paths used to be written from a repository root, which is a
directory an operator who downloaded the zip does not have.

```powershell
cd $env:LOCALAPPDATA\RCSL-AI-Nexus\client-tools   # or the checkout's scripts\windows\codex-app
powershell.exe -NoProfile -STA -ExecutionPolicy Bypass `
  -File .\Start-CodexAppSwitcher.ps1
```

The scripts do not require Node.js, Python, PowerShell 7, administrator rights,
or a separately installed Codex CLI. `winget` and Microsoft Store access are
needed only when the App must be installed.

Run the doctor without network checks:

```powershell
powershell.exe -NoProfile -STA -File .\Test-CodexAppConnection.ps1
```

Add DNS, TLS, health, and authenticated model-catalogue checks:

```powershell
powershell.exe -NoProfile -STA -File .\Test-CodexAppConnection.ps1 `
  -ProjectPath C:\work\the-project -Online -Authenticated
```

The authenticated form prompts for the API key with hidden input. There is no
API-key command-line parameter because command lines are observable by other
processes and frequently copied into shell history.

Run the configuration-handling suite:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\Invoke-CodexAppSwitcherTests.ps1
```

It must be run on Windows PowerShell 5.1, which is the host the switcher itself
targets and the host on which its first three faults were visible at all. See
the runbook, section 6.1 (`docs/runbooks/windows-codex-app-switcher.md`)
for what the suite covers and how it was checked against the defects it exists
to catch.

## Safety properties

- The App is asked to exit through its normal window close path. It is never
  force-terminated. On the measured build there is no window to ask, because the
  App sits in the notification area, so the switcher stops immediately and says
  to quit it from the tray icon. Quit the App before switching in either
  direction.
- `config.toml` is copied before the first Nexus switch in a cycle.
- Changes are written through a same-directory temporary file.
- Only top-level `model` and `model_provider` plus the
  `[model_providers.rcsl_nexus_switcher]` table are managed. The dedicated ID
  avoids overwriting a pre-existing `rcsl` provider.
- A per-session mutex prevents two switcher windows from interleaving writes.
- Missing, malformed, or unknown recovery state fails closed. The tool never
  guesses which manually configured model/provider should be deleted.
- Advanced TOML forms the formatting-preserving editor cannot handle
  unambiguously are rejected before any backup, state, or configuration write.
- Existing plugins, MCP servers, permissions, project trust entries, and App
  preferences are retained.
- The Nexus key is not written to TOML, state JSON, the backup, or logs. It is
  installed only in the environment inherited by the newly launched App.
- The GUI necessarily holds the pasted key briefly in process memory while it
  converts, validates, and passes it. Closing the GUI releases that process; the
  guarantee is no persistence at rest, not forensic erasure of managed memory.
- Restoring OpenAI removes the key from the launch environment and restores the
  top-level selection captured before the switch.
- The inactive RCSL provider table remains after restoration so App tasks
  created in Nexus mode can still resolve their provider metadata.
- A legacy user-level key created with `setx` is reported and can be removed
  explicitly. A machine-level key is reported but never removed without an
  elevated operator action.

Runtime state and backups are kept outside the repository:

```text
%LOCALAPPDATA%\RCSL-AI-Nexus\codex-app-switcher\
```

The newly entered Nexus key is never stored there. The whole-file recovery copy
can contain credentials that were already present in `config.toml`; the state
directory is therefore created with an ACL granting only the current Windows
user access. Treat backups as sensitive and remove obsolete ones deliberately.

## Boundary of automation

The doctor can prove that the package, user-level configuration, network, TLS,
key, and `code` capability are available. It warns when a project
`.codex/config.toml` defines a higher-precedence `model`; project-local provider
and authentication keys are ignored by Codex. It cannot prove the complete desktop App
agent loop. The App adds its own plugins, hidden model slots, tool definitions,
and picker behavior. After switching, create a new App task and request a real
file operation; a greeting proves only text generation.

Direct `ChatGPT.exe` launch and key inheritance were measured on 2026-08-29
against `OpenAI.Codex` `26.825.4187.0`: the App started, and its main process
plus most of its children carried the process-scoped `RCSL_API_KEY`. Neither is
a documented OpenAI compatibility contract, and one utility child carried no
inherited environment at all, so what the app-server does with the key is still
unproven. Startup confirmation detects a changed path or an immediate
managed-config rewrite, but the integration remains experimental until the
interactive App task passes on the installed build. WSL agent mode is outside
the verified scope.

## Source basis

- OpenAI's [Windows App documentation](https://learn.chatgpt.com/docs/windows/windows-app)
  defines the supported native/WSL2 modes, the Store installation command, and
  how native App and CLI configuration sharing differs from WSL.
- [Basic configuration](https://learn.chatgpt.com/docs/config-file/config-basic)
  defines general precedence, while [project config rules](https://learn.chatgpt.com/docs/config-file/config-advanced#project-config-files-codexconfigtoml)
  specify that project-local provider and authentication keys are ignored.
- [Advanced configuration](https://learn.chatgpt.com/docs/config-file/config-advanced#custom-model-providers)
  and the [configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)
  define custom-provider fields including `base_url`, `env_key`, and
  `wire_api = "responses"`.
- The [`CODEX_HOME` reference](https://learn.chatgpt.com/docs/config-file/environment-variables#core-locations)
  identifies the state directory used by the CLI, IDE extension, and
  app-server.
- `OpenAI.Codex`, `app\ChatGPT.exe`, the alias fallback, and propagation of a
  directly launched process environment into the internal app-server are not
  documented by OpenAI. They remain project observations or hypotheses and are
  guarded by discovery, startup checks, and a required interactive App task.

The primary runbook's
source and evidence matrix, section 10 of the runbook
classifies every external and project-specific claim. Its official links were
rechecked on 2026-08-25.

The detailed operator workflow and recovery procedure are in
`docs/runbooks/windows-codex-app-switcher.md` in the repository, and on the management UI's agent-setup page.
