# Windows runbook: Experimentally switch Codex App between RCSL AI Nexus and OpenAI

This runbook covers the Windows desktop App distributed as the
`OpenAI.Codex` Microsoft Store package and displayed as ChatGPT/Codex. It does
not cover Codex on the web, which runs on OpenAI infrastructure and cannot read
local provider configuration.

OpenAI's [Windows App documentation](https://learn.chatgpt.com/docs/windows/windows-app)
is the authoritative source for supported Windows installation and operating
modes. The `OpenAI.Codex` package identity and executable layout named here were
observed on one machine and one build on 2026-08-29, which makes them
measurements rather than identifiers that documentation promises. Section 2
records what that measurement covered and section 10 classifies every claim.

The switcher exists because project measurements found that editing
`%USERPROFILE%\.codex\config.toml` while the App is running is not a safe
procedure. On the measured builds, the App updated plugin and MCP state and
rewrote the file. A provider block inserted into an in-memory configuration the
App had already loaded could disappear at the next rewrite. This switcher's
guarded workflow is therefore a transaction around an App restart: validate,
close, back up, update, launch, and retain recovery state.

## 1. What the switch changes

Nexus mode selects one capability and the custom provider:

```toml
model = "code"
model_provider = "rcsl_nexus_switcher"

[model_providers.rcsl_nexus_switcher]
name = "RCSL AI Nexus"
base_url = "https://llmapi.rcsl.online/v1"
env_key = "RCSL_API_KEY"
wire_api = "responses"
```

`model` is a Nexus capability, not the backing Ollama or MLX model. Routing on
the server decides which registered model serves `code`.

The provider fields follow OpenAI's documented
[custom model-provider schema](https://learn.chatgpt.com/docs/config-file/config-advanced#custom-model-providers).
The [configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)
defines `model_provider`, `model_providers.<id>.base_url`, `env_key`, and
`wire_api`; `responses` is the only currently documented wire API.

The switcher passes `RCSL_API_KEY` only to the new App process. It does not use
`setx`, modify the user or machine environment, write the key into TOML, or
replace ChatGPT authentication. The Nexus key authenticates the custom model
provider; it is not an OpenAI API key and not a ChatGPT session.

OpenAI mode restores the top-level `model` and `model_provider` lines captured
before Nexus mode and starts the App with no process-scoped Nexus key. It does
not run `codex logout`, delete `auth.json`, sign out of ChatGPT, remove plugins,
or reset App state.

The `[model_providers.rcsl_nexus_switcher]` table is intentionally retained while inactive.
App tasks created in Nexus mode may continue to name that provider. Removing
the definition can make the App fail while reopening one of those tasks even
though new tasks should use OpenAI.

## 2. Requirements

- A Windows release supported by the current ChatGPT desktop App. This project
  does not independently establish the App's minimum Windows version.
- Windows PowerShell 5.1 (`powershell.exe`). PowerShell 7 is not claimed by
  this runbook.
- Windows-native agent mode. WSL agent-mode environment inheritance has not
  been verified by this project.
- An RCSL AI Nexus key scoped to `code`.
- Network access to `https://llmapi.rcsl.online`.
- `winget` and Microsoft Store access only if Codex App is not installed.

OpenAI documents the App's native Windows and WSL2 agent modes, but does not
document the process-environment inheritance on which this switcher's native
launch path relies. This project therefore limits its claim to Windows-native
mode pending the interactive acceptance test in section 7.

The switcher currently attempts discovery through the `OpenAI.Codex` AppX identity. If AppX
discovery is unavailable, it derives the package root from the `codex.exe`
execution alias. Package installation paths contain the App version and must
never be hard-coded. The Store ID below is documented by OpenAI.

Everything this section used to hold open was measured on 2026-08-29, on one
Windows 11 machine running `OpenAI.Codex` `26.825.4187.0`, first in a redirected
`CODEX_HOME` and then, with a real Nexus key, against the operator's own
configuration:

- The package identity and layout are as assumed. `AppxManifest.xml` names
  `app/ChatGPT.exe` as its `Windows.FullTrustApplication` entry point.
- Launching that executable directly does start the App, which came up as nine
  processes and passed the switcher's own startup confirmation.
- The process-scoped key reaches the App and, decisively, reaches
  `codex.exe app-server` -- the internal component that actually issues the
  request. Its environment block, read out of its PEB, carried `RCSL_API_KEY`,
  and it held an established TLS connection to the gateway address.
- The agent loop works end to end. A new App task asked to read a file ran
  `cat README.md` and returned a correct summary of it, which is the acceptance
  step section 7 describes.

One machine, one build, one run. This is a measurement rather than a
compatibility contract, and the App updates itself.

The app-server is worth naming, because it is not where a search for the App
would look. It runs from `%LOCALAPPDATA%\OpenAI\Codex\bin\<hash>\codex.exe`,
outside the package directory entirely, and it is the process that reads
`config.toml`. The switcher counts it as part of the App for exactly that
reason; an interactive `codex` CLI session is not counted, since only the App
starts the `app-server` subcommand.

When installation is required, the switcher runs the command in OpenAI's
[Windows App download instructions](https://learn.chatgpt.com/docs/windows/windows-app#download-the-chatgpt-desktop-app):

```powershell
winget install --id 9PLM9XGG6VKS --source msstore `
  --accept-package-agreements --accept-source-agreements
```

Installation can still require Microsoft Store availability or organizational
approval. A successful `winget` exit is followed by package rediscovery; it is
not treated as proof by itself.

## 3. Start the GUI

Operators with a repository checkout can launch from its root:

```powershell
powershell.exe -NoProfile -STA -ExecutionPolicy Bypass `
  -File .\scripts\windows\codex-app\Start-CodexAppSwitcher.ps1
```

Operators following the deployed management UI do not need a checkout. Step 2 of
the agent-setup page links a zip of these scripts, served by the deployment
itself from `GET /admin/client-tools/windows-codex-app`. Unzip it and launch the
switcher from wherever it landed:

```powershell
$toolsRoot = Join-Path $env:LOCALAPPDATA 'RCSL-AI-Nexus\client-tools'
$zip = Get-ChildItem "$env:USERPROFILE\Downloads\rcsl-codex-app-tools*.zip" |
  Sort-Object LastWriteTime -Descending | Select-Object -First 1
Expand-Archive -LiteralPath $zip.FullName -DestinationPath $toolsRoot -Force
powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -File `
  "$toolsRoot\Start-CodexAppSwitcher.ps1"
```

The newest matching download, rather than the plain filename. A second download
after a deployment update is saved as `rcsl-codex-app-tools (1).zip`, so naming
the exact file would extract the older archive over the newer one and launch the
previous switcher, reporting nothing. A redirected Downloads folder — OneDrive
Known Folder Move, which is usual on a managed machine — means pointing the
second line at wherever the browser actually saved it.

The download comes from the image the deployment is running, over the origin and
session the operator is already signed in to, and the endpoint requires that
session. It replaced an `Invoke-WebRequest` of the whole repository archive from
GitHub `main`, which fetched a deployment's worth of files to deliver five,
named no version anyone could refer to, and sent somebody who trusts this
platform to a different origin for a script that will hold their API key. It
also means the operator path no longer depends on the repository staying public.

The archive is byte-for-byte reproducible: entry order, timestamps, mode,
originating system and line endings are all fixed, so an archive built from a
checkout equals the one the deployment serves. That was measured across a
Windows checkout and the Linux image rather than assumed, and the first attempt
was not equal — nor was the second. Pinning the zip's own metadata left the file
*contents* still coming from whatever the checkout held: these files were CRLF in
a Windows working tree and LF in the index, so every entry differed while the
metadata test passed. `.gitattributes` now fixes them to CRLF in every working
tree, and the archive builder applies the same rule again on the way in, so the
served bytes do not depend on the build host having honoured a git attribute.

Inspect the scripts before running them. They will hold an API key, and the fact
that they arrived over an authenticated origin is provenance, not a warrant.

The GUI shows the detected App version, whether it is running, the user-level
top-level provider selection, and whether a persistent legacy
`RCSL_API_KEY` exists.

A trusted project's `.codex/config.toml` may define `model` with higher
precedence than the user file, changing the effective Nexus capability. Codex
explicitly ignores project-local `model_provider` and `model_providers`, so a
project file cannot redirect this switcher's provider or authentication. Enter
the project directory in the GUI so Doctor can report project files that
actually define a top-level `model`. This follows OpenAI's documented
[project-config rules](https://learn.chatgpt.com/docs/config-file/config-advanced#project-config-files-codexconfigtoml)
and [configuration precedence](https://learn.chatgpt.com/docs/config-file/config-basic#configuration-precedence).

`ExecutionPolicy Bypass` applies only to that PowerShell process. The script
does not change the machine or user execution policy.

## 4. Connect the App to Nexus

1. Finish, cancel, or hand off every active App task, then **quit Codex App from
   its notification-area icon**. Provider changes are not safe while work is
   running, and on the measured build the switcher cannot close the App for you:
   see section 4.2.
2. Enter the gateway base URL. Leave the production default unchanged unless
   an operator has supplied another deployment.
3. Enter `code` as the capability unless the issued key and routing policy are
   explicitly for another agent-capable capability.
4. Paste the Nexus API key into the masked field.
5. Leave **Validate GET /v1/models before changing the App** enabled.
6. Select **Connect App to RCSL AI Nexus**.

The switcher then performs these operations in order:

1. Discover or install the App.
2. Read `config.toml` and the recovery state, and refuse now if either is a
   form the switcher will not own. It does this by rehearsing the entire edit
   against a copy of the document and discarding the result, so that every
   refusal decidable by reading is decided here, before the operator's App is
   touched, and a refusal costs nothing. Running the transformation twice is
   cheaper than closing somebody's App to tell them about a duplicate line.
3. Validate the key against `GET /v1/models` and require the selected
   capability in the response.
4. Ask any ChatGPT App window to close normally, or stop immediately with
   instructions when the App exposes no window to ask (section 4.2).
5. Refuse to continue if any App process remains after the timeout.
6. Re-read `config.toml` and repeat the checks. The App rewrites the file as it
   exits, so the document validated in step 2 is not necessarily the document
   about to be edited.
7. Copy a UTF-8 text snapshot of the pre-switch configuration under
   `%LOCALAPPDATA%\RCSL-AI-Nexus\codex-app-switcher\backups`.
8. Record the original top-level model/provider lines in state without the
   newly entered Nexus API key.
9. Update the selection and RCSL provider definition with an atomic file move.
10. Start `ChatGPT.exe` directly with a process-scoped `RCSL_API_KEY`.
11. Confirm a process under the discovered package path appears and the managed
    configuration projection survives startup.
12. Restore the launcher's own process environment immediately.

### 4.1 What the switcher will not edit

The switcher edits `config.toml` line by line rather than through a TOML
parser, so it refuses any document whose meaning a line cannot carry. The
refusals are narrow on purpose, because the documents being refused belong to
the operator and most of what is in them was written by the App itself.

Accepted, and normal in an App-written file: quoted table headers such as
`[projects.'c:\dev\my project']` and `[plugins."browser@openai-bundled"]`,
quoted keys inside tables the switcher does not own, blank lines anywhere,
array-of-tables headers other than `model_providers`, and any line ending
convention.

Refused, with the line number and the reason:

| Form | Why |
|---|---|
| A multiline string (`"""` or `'''`) | Its content can spell a table header or a `model` key that is not one. |
| A quoted key in the top-level section, or inside `[model_providers.rcsl_nexus_switcher]` | It can spell `model`, `model_provider`, or a provider field the switcher would then write twice. |
| A multi-line array in either of those two places | Its continuation lines cannot be told apart from table headers, and a header is what decides where the top-level section ends. |
| `model_providers` defined inline, through a dotted key, or as an array of tables | The provider table is the only shape the switcher can add to and remove from. |
| A table nested under `[model_providers.rcsl_nexus_switcher]` | The switcher owns that table and would not preserve a child of it. |
| A table-header segment written as a basic string containing a backslash escape | Resolving it needs full TOML escape processing; the switcher fails closed rather than miss a provider hiding under an escaped spelling. |

The rehearsal in step 2 adds the refusals that only appear once the edit is
attempted, and moves them ahead of the App being closed:

| Form | Why |
|---|---|
| Two top-level `model` or `model_provider` keys | The switcher would not know which one it is meant to replace, and replacing one leaves the other selecting something else. |
| A second `[model_providers.rcsl_nexus_switcher]` table | Same ambiguity, for the table it owns. |
| A duplicated key inside that table | Same again, for a field it writes. |
| `experimental_bearer_token`, or `requires_openai_auth = true`, inside that table | Both conflict with the `env_key` authentication the switcher configures. |
| `[model_providers.rcsl_nexus_switcher.auth]` | The switcher would not preserve it, and it contradicts `env_key`. |

A refusal names the line and what to change. None of them modifies anything, and
none of them closes the App first.

### 4.2 The switcher cannot close this App for you

The design has always been that the App is asked to close and never
force-terminated. On the measured build, asking is not something the switcher
can do at all, and it is better to know that than to discover it after a
timeout.

`OpenAI.Codex` `26.825.4187.0` sits in the notification area, and it was
measured in both of the states it can be in. Neither closes.

Started without a profile, it showed no visible window at all. Windows reports a
main window only when one is visible and unowned, so there was nothing for the
switcher to ask, and its polite close had no recipient.

Started with the real profile, it did show a window, and the close request
reached it. Forty seconds later all nine processes and the app-server were still
running. Posting `WM_CLOSE` to those windows directly did not end it either,
which is ordinary behavior for a program whose window closing means "hide to the
tray".

So the switcher asks where there is something to ask, tells the operator
immediately where there is not, and in both cases says the same thing: quit
Codex App from its tray icon, because closing its window is not the same act.
It still terminates nothing. Quit the App before switching in either direction.

The switcher relies on the App and its child app-server inheriting the key from
the directly launched process. Later terminals, unrelated applications, and a
normally launched App do not receive that process-scoped environment. The
launcher's startup checks prove only that the expected App process appears and
the managed configuration survives startup; only section 7's real App task can
prove that the internal app-server consumed the inherited key.

OpenAI documents that the Windows App and a native Windows CLI use the same
Codex home, normally `%USERPROFILE%\.codex`, while a WSL CLI defaults to the
Linux home and does not automatically share it; see
[Share config, auth, and sessions with WSL](https://learn.chatgpt.com/docs/windows/windows-app#share-config-auth-and-sessions-with-wsl).
The [`CODEX_HOME` reference](https://learn.chatgpt.com/docs/config-file/environment-variables#core-locations)
also states that the CLI, IDE extension, and app-server use that directory for
configuration and other state. While Nexus mode is active, a separately
launched native CLI therefore sees `model_provider = "rcsl_nexus_switcher"` but
does not inherit the GUI's key. Either give that CLI process its own
`RCSL_API_KEY` or restore OpenAI before using it. The switcher does not install
or operate the npm CLI.

The masked field prevents shoulder-surfing and the tool never persists the key.
Like any GUI text field, it necessarily holds the pasted value briefly in
managed process memory while converting and validating it. Close the switcher
after launch; this design promises no credential at rest, not forensic memory
erasure.

Create a **new task** after the App starts. An existing task retains the
provider and model metadata it was created with.

## 5. Switch the App back to OpenAI

1. Finish or cancel active Nexus work.
2. Open the switcher again.
3. If an older manual setup used `setx RCSL_API_KEY`, optionally select the
   legacy-key removal checkbox.
4. Select **Switch App back to OpenAI**.

The switcher closes the App, restores the exact top-level selection captured
before the Nexus switch, preserves the provider definition, and launches the
App without a Nexus key.

If state is absent, malformed, or from an unsupported schema while the managed
provider is selected, restoration fails closed. The tool does not guess what a
previous model was, does not delete a manually configured provider, and never
restores a whole stale backup over newer App-managed plugin or MCP changes. Use
the manual recovery procedure in section 9.

**What "malformed" means, since it used not to mean much.** A state is read as
usable only when its schema version matches, every property the switcher relies
on is present, and its mode is one of the three it writes: `preparing-rcsl`,
`rcsl`, `openai`. Any other mode is a refusal. The check previously asked only
whether the mode was one of the two active ones, so a truncated or hand-edited
state answered "not active", and the next switch to Nexus treated it as no state
at all and overwrote the recovery metadata that was the way back. An unknown mode
now stops the switch instead, with the state left where it is.

**Both refusals are reached before the App is closed.** The state is read, and
checked against the active `CODEX_HOME`, in the same preflight that rehearses the
document edit. A state belonging to another profile used to pass that preflight
and be rejected afterwards, which cost the operator a closed App for a refusal
that was decidable by reading. The check is repeated after the close, because the
App rewrites `config.toml` as it exits; it is the same function both times, so the
two cannot come to disagree.

After restoration, create a new task and confirm the expected OpenAI model is
available. Do not use the continued existence of the inactive RCSL provider
table as a mode signal; the selected top-level provider is the signal.

## 6. Run the doctor

Local, read-only checks:

```powershell
powershell.exe -NoProfile -STA -File `
  .\scripts\windows\codex-app\Test-CodexAppConnection.ps1
```

Add DNS, TLS, unauthenticated health, and authenticated model-catalogue checks:

```powershell
powershell.exe -NoProfile -STA -File `
  .\scripts\windows\codex-app\Test-CodexAppConnection.ps1 `
  -ProjectPath C:\work\the-project -Online -Authenticated
```

The key prompt is a masked Windows dialog. There is intentionally no API-key parameter: a
command-line secret is observable in process listings and likely to be retained
in shell history.

The doctor reports:

- Windows support;
- package identity, version, and discovery method;
- App process state;
- `config.toml` path and selected model/provider;
- complete managed-provider values and state/config drift;
- `.codex/config.toml` files from the supplied project path that define a
  higher-precedence top-level `model`;
- recovery-state and backup availability, and whether the backup still hashes to
  the value recorded when it was taken, since a truncated or edited backup
  otherwise looks exactly like an intact one until it is needed;
- legacy user- or machine-level key presence, without reading the value;
- DNS, TLS, and `/healthz` when `-Online` is used;
- authenticated `/v1/models` capability visibility when `-Authenticated` is
  used.

`-AsJson` emits machine-readable results and exits non-zero if any check is
`FAIL`.

### 6.1 The suite that runs without an App

The doctor inspects one machine. The configuration handling underneath it is
covered separately, and that suite is what CI runs:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\windows\codex-app\Invoke-CodexAppSwitcherTests.ps1
```

It touches no App, no network, no registry, no `config.toml`, and no recovery
state; it calls the module's configuration functions directly against fixtures
in the shape the App writes. It deliberately uses no test framework, because
the faults it pins were visible only under Windows PowerShell 5.1 with
`Set-StrictMode -Version Latest`, and that is the host it therefore runs on
with nothing to install first.

The suite has been checked against the defects it exists to catch. With each of
the nine reintroduced one at a time, it fails 14, 17, 3, 7, 2, 1, 1, 1 and 1 of
its cases respectively, and never zero. A suite that passes on the broken code
proves nothing, and this one was measured rather than assumed.

The four defects closed on 2026-08-30 were measured the same way against the
enlarged suite: removing the mode allowlist fails 2 cases, removing the
required-property check 1, letting restoration fall back to the enable path's
looser rule 1, and moving the restore path's state validation back behind
`Stop-CodexAppGracefully` 1. Those figures come from PowerShell 7.6 on macOS,
which runs all 76; the `windows-client-tools` job is what runs them on the 5.1
host the switcher targets.

One of the 76 exists because a review pointed out that the rest were arguing
about the wrong object. The required-property check fails closed, and the state
it sees is never the `[pscustomobject]` a test builds — it is always
`ConvertTo-Json`, a file, and `ConvertFrom-Json` again. If that round trip ever
dropped a key whose value is `$null`, every operator whose `config.toml` had no
`model_provider` line, which is the ordinary first switch, would be refused both
the switch and the restore while this suite stayed green. One case now writes
and re-reads a real file through the two functions `Save-SwitcherState` and
`Get-SwitcherState` use, without touching the recovery state directory.

Four of its cases assert over the module's own source rather than by calling
it, following the precedent in
`backend/tests/unit/test_refusal_identity_and_permissions.py`. They exist
because the properties concerned belong to the call sites and not to any
function: that both switch paths validate the document before closing the App,
that the restore path validates the recovery state before closing it and again
afterwards, and that nothing in the module reads a file with `Get-Content`,
whose Windows PowerShell default decodes a BOM-less file in the system codepage.
Exercising a helper cannot hold any of them, since the orchestration around them
needs a real App to run.

The `windows-client-tools` CI job runs it on `windows-latest`, together with
PSScriptAnalyzer under
[`scripts/windows/PSScriptAnalyzerSettings.psd1`](../../scripts/windows/PSScriptAnalyzerSettings.psd1).
Every other CI job runs on Linux, so before that job existed a green pipeline
said nothing whatever about this directory.

## 7. What the doctor cannot prove

An HTTP check can prove the network, perimeter, key, capability, and routing
catalogue. It cannot prove the desktop App-specific agent loop. The App may add:

- plugins and MCP tools;
- hundreds of tool definitions resent on every turn;
- hidden model slots such as automatic review;
- a model picker that overrides the configured model;
- behavior changed by a self-update since the last measured build.

On 2026-08-29 this gate was walked through rather than reasoned about, and it
passed. The acceptance step below was run on `26.825.4187.0` with a real Nexus
key against the operator's own configuration: a new App task asked to read a
file ran `cat README.md` and returned a correct summary of it. The App's model
picker showed the custom provider rather than overriding it, and
`codex.exe app-server` held an established connection to the gateway with
`RCSL_API_KEY` in its environment. Tool call, translation, inference and result
all worked.

That does not retire this section. It closes it for one build on one machine on
one day, against one capability. The App self-updates, the picker is a UI the
operator can change, and the list above describes things that appear and
disappear between versions. The step is cheap and the failure it catches is
silent, so run it after switching, and run it again after the App updates
itself. One figure worth recording from the passing run: the task took five
minutes and seventeen seconds, which is the local runtime rather than the
switcher, and is what an operator should expect to wait.

After switching, request a real file operation in a new App task, for example:

> Read README.md and summarize the local development requirements.

A greeting proves only that text generation works. A file operation proves
that the App supplied tools, the Nexus Responses translation carried them, the
model emitted a tool call, the App executed it, and the result completed the
loop.

If the request fails, retain its request ID and use the management UI Refusals
screen. Do not retry a `413 context_too_long`, `429 quota_exceeded`, or
`403 capability_not_issued` without reading its stored reason.

## 8. Failure guide

| Symptom | Meaning and action |
|---|---|
| "none of them exposes a window to close" | Expected on the measured build, which sits in the notification area (section 4.2). Quit Codex App from its tray icon and retry. Nothing was changed. |
| App is still running after being asked to close | A window was asked and the App did not exit within the timeout. Resolve active work and quit from the tray; the tool will not force-kill it. |
| A message names a `config.toml` line and a TOML form | One of the refusals in section 4.1. Nothing was changed and the App was not closed. Edit that line, or keep using the CLI path in [Connect an agent client](./connect-an-agent-client.md). |
| The same refusal appears only after the App closes | The App rewrote `config.toml` on exit and introduced the form. Report the line: a shape the App itself writes belongs in section 4.1's accepted list, not in its refused one. |
| App is absent and winget is unavailable | Install Microsoft App Installer or use the Store manually, then retry. |
| `GET /v1/models` returns 401 | The key is wrong, expired, revoked, or outside its CIDR. The public response deliberately does not distinguish them. |
| `code` is absent from `/v1/models` | The key does not hold that capability or no routable policy is visible to it. Do not change the App yet. |
| `403 capability_not_issued` names an OpenAI model | The App picker or a hidden slot overrode `model = "code"`. Inspect the exact refused name before changing permissions. |
| `413 context_too_long` on a new task | App-injected tool definitions may dominate the prompt. Starting another task will not reduce a tool list resent on every turn. |
| App reopens an old task with a missing provider | Preserve `[model_providers.rcsl_nexus_switcher]`, then start a new task. Do not delete global state or authentication. |
| A machine-level key remains | Remove it from an elevated shell only after confirming no other integration uses it. |
| The App changes behavior after an update | Record the App build and plugin set. Re-run the doctor and compare with another machine before attributing the change to Nexus. |

## 9. Recovery

The tool never automatically overwrites current configuration with a complete
backup. App-managed plugin, MCP, permission, and preference entries may have
changed after the backup was taken. Whole-file restoration is therefore a
manual disaster-recovery action, not the normal OpenAI switch.

Recovery artifacts are under:

```text
%LOCALAPPDATA%\RCSL-AI-Nexus\codex-app-switcher\
├── state.json
└── backups\config.toml.before-rcsl-<UTC timestamp>
```

`state.json` contains paths, mode, managed-projection hashes, original
model/provider lines, App version, the validated credential-free gateway
origin, and capability. It never contains the newly entered Nexus key or
ChatGPT authentication. Treat it as sensitive anyway: original TOML lines are
preserved verbatim and could include an operator-written secret in a comment.

The whole-file backup can contain credentials that were already present in
`config.toml`. The switcher protects its state directory with a current-user-only
Windows ACL, but operators must still treat every backup as sensitive.

If manual recovery is necessary:

1. Exit Codex App completely.
2. Copy the current `config.toml` aside with a timestamp.
3. Read `state.json` and the named backup; do not assume the newest-looking file
   is the pre-switch side of the transaction.
4. Prefer restoring only `model` and `model_provider`.
5. Preserve `[model_providers.rcsl_nexus_switcher]` while any Nexus task remains.
6. Never delete `auth.json`, `.codex-global-state.json`, sessions, or
   conversations as a provider-switch recovery step.

Revoking the key in the Nexus management UI is the only server-side disconnect.
Removing configuration from one Windows machine does not invalidate copies of
the key or configuration elsewhere.

## 10. Source and evidence matrix

The following classification prevents project observations from being mistaken
for OpenAI compatibility guarantees. Official pages were rechecked on
2026-08-25.

| Claim | Evidence class | Source |
|---|---|---|
| The Windows App supports native Windows and WSL2 agent modes. | OpenAI documentation | [Windows App](https://learn.chatgpt.com/docs/windows/windows-app) |
| The Microsoft Store install command uses Store ID `9PLM9XGG6VKS`. | OpenAI documentation | [Download the Windows App](https://learn.chatgpt.com/docs/windows/windows-app#download-the-chatgpt-desktop-app) |
| Native App and native CLI normally share `%USERPROFILE%\.codex`; WSL defaults to a separate Linux home. | OpenAI documentation | [Share config, auth, and sessions with WSL](https://learn.chatgpt.com/docs/windows/windows-app#share-config-auth-and-sessions-with-wsl) |
| `CODEX_HOME` controls the state directory used by the CLI, IDE extension, and app-server. | OpenAI documentation | [`CODEX_HOME`](https://learn.chatgpt.com/docs/config-file/environment-variables#core-locations) |
| Trusted project configuration can override `model`, while project-local provider and auth keys are ignored. | OpenAI documentation | [Project config files](https://learn.chatgpt.com/docs/config-file/config-advanced#project-config-files-codexconfigtoml) and [Configuration precedence](https://learn.chatgpt.com/docs/config-file/config-basic#configuration-precedence) |
| Custom providers support `base_url`, `env_key`, and `wire_api = "responses"`; `env_key` names an environment variable rather than containing its secret. | OpenAI documentation | [Custom model providers](https://learn.chatgpt.com/docs/config-file/config-advanced#custom-model-providers) and [Configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference) |
| The installed App exposes the `OpenAI.Codex` AppX identity and an `app\ChatGPT.exe` executable. | Project measurement, 2026-08-29 | Observed on one Windows 11 machine: `Get-AppxPackage -Name OpenAI.Codex` returned `26.825.4187.0`, and that package's `AppxManifest.xml` names `app/ChatGPT.exe` as the `Windows.FullTrustApplication` entry point. One machine and one build; still not an OpenAI compatibility contract |
| Executing the packaged executable directly starts the App. | Project measurement, 2026-08-29 | A full `Enable-RcslCodexApp` in a redirected `CODEX_HOME` launched it as eight Chromium processes and passed the switcher's own startup confirmation. Package activation is bypassed by this path, so a build could stop tolerating it without notice |
| The process-scoped key reaches the component that issues the request. | Project measurement, 2026-08-29 | `codex.exe app-server`, a child of ChatGPT.exe running from `%LOCALAPPDATA%\OpenAI\Codex\bin`, carried `RCSL_API_KEY` in its PEB environment block and held an established connection to the gateway address while a task ran |
| The App's agent loop works against Nexus. | Project measurement, 2026-08-29 | A new task on the operator's own configuration, with a real `code` key, ran `cat README.md` and returned a correct summary. Model picker showed the custom provider. Elapsed five minutes seventeen seconds. One build, one capability, one run: section 7 stays as a step to repeat, not a box that is now ticked |
| The switcher can close a running App. | Refuted by measurement, 2026-08-29 | Measured in both states: with no visible window there is nothing to ask, and with a visible window `CloseMainWindow` reached it and all nine processes plus the app-server were still running forty seconds later. `WM_CLOSE` posted directly did not end it either. The operator quits it from the tray; the switcher says so rather than waiting (section 4.2) |
| Counting only `ChatGPT.exe` under the package directory answers "has the App closed". | Refuted by measurement, 2026-08-29 | The process that reads `config.toml` is `codex.exe app-server`, which lives outside the package. It was invisible to that count. On this build it exited before its parent, so no unsafe window was observed at 200 ms sampling, but the ordering was not something the switcher checked. It now counts the app-server too |
| The configuration handling accepts what the App writes and refuses only what a line-oriented edit cannot carry. | Repository implementation, under test | 76 cases in [`Invoke-CodexAppSwitcherTests.ps1`](../../scripts/windows/codex-app/Invoke-CodexAppSwitcherTests.ps1), run by the `windows-client-tools` CI job on Windows PowerShell 5.1, and measured against each reintroduced defect (section 6.1) |
| A directly launched packaged executable passes `RCSL_API_KEY` through to the App's internal app-server. | Project hypothesis requiring interactive acceptance | Launch code in [`CodexAppSwitcher.Common.psm1`](../../scripts/windows/codex-app/CodexAppSwitcher.Common.psm1) plus section 7 of this runbook; not documented by OpenAI |
| The App may rewrite user configuration and inject plugins, MCP servers, hidden model slots, and large tool sets. | Project-observed behavior | Historical measurements in [Connect an agent client](./connect-an-agent-client.md#32-the-same-sharing-in-the-direction-that-can-break-it); not presented as OpenAI guarantees |
| WSL agent mode inherits a key injected into a native Windows App process. | Unknown / out of scope | No supporting OpenAI documentation or completed project acceptance test |
| CLI profiles load `$CODEX_HOME/<profile-name>.config.toml` and do not use `[profiles.<name>]`. | OpenAI documentation | [Profiles](https://learn.chatgpt.com/docs/config-file/config-advanced#profiles) |
| Nexus exposes the Responses and model-catalogue paths required by this integration. | Repository implementation | [`/v1/responses`](../../backend/app/interfaces/http/routers/responses/route.py) and [`/v1/models`](../../backend/app/interfaces/http/routers/chat/route.py) route sources |
| The doctor's unauthenticated online checks reach the production gateway. | Project measurement, 2026-08-29 | `Test-CodexAppConnection.ps1 -Online` resolved `llmapi.rcsl.online` and got HTTP 200 from `/healthz` over a trusted TLS connection. The authenticated `/v1/models` check was not run for this change |
