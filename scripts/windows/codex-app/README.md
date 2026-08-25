# Windows Codex App switcher

This directory contains Windows-only operator tools for switching the local
Codex desktop app between the built-in OpenAI provider and RCSL AI Nexus.

The tools are deliberately App-first. The bundled `codex.exe` is used only as
an installation discovery fallback; these scripts do not install the npm Codex
CLI and do not use CLI profiles as a substitute for changing the desktop app.
The App and CLI share `config.toml`, so the selected provider is also visible to
a later CLI process. The switcher's process-scoped key is inherited only by the
App it starts; a separately launched CLI needs its own process-scoped key or an
OpenAI restoration first.

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

## Launch

From Windows PowerShell:

```powershell
powershell.exe -NoProfile -STA -ExecutionPolicy Bypass `
  -File .\scripts\windows\codex-app\Start-CodexAppSwitcher.ps1
```

The scripts do not require Node.js, Python, PowerShell 7, administrator rights,
or a separately installed Codex CLI. `winget` and Microsoft Store access are
needed only when the App must be installed.

Run the doctor without network checks:

```powershell
powershell.exe -NoProfile -STA -File `
  .\scripts\windows\codex-app\Test-CodexAppConnection.ps1
```

Add DNS, TLS, health, and authenticated model-catalogue checks:

```powershell
powershell.exe -NoProfile -STA -File `
  .\scripts\windows\codex-app\Test-CodexAppConnection.ps1 `
  -ProjectPath C:\work\the-project -Online -Authenticated
```

The authenticated form prompts for the API key with hidden input. There is no
API-key command-line parameter because command lines are observable by other
processes and frequently copied into shell history.

## Safety properties

- The App is asked to exit through its normal window close path. It is never
  force-terminated.
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
`.codex/config.toml` can override the user default. It cannot prove the complete desktop App
agent loop. The App adds its own plugins, hidden model slots, tool definitions,
and picker behavior. After switching, create a new App task and request a real
file operation; a greeting proves only text generation.

Direct `ChatGPT.exe` launch and process-scoped key inheritance rely on observed
package internals, not a documented OpenAI compatibility contract. Startup
confirmation detects a changed path or an immediate managed-config rewrite, but
the integration remains experimental until the interactive App task passes on
the installed build. WSL agent mode is outside the verified scope.

The detailed operator workflow and recovery procedure are in
[`docs/runbooks/windows-codex-app-switcher.md`](../../../docs/runbooks/windows-codex-app-switcher.md).
