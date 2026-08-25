# Windows runbook: Switch Codex App between RCSL AI Nexus and OpenAI

This runbook covers the Windows desktop App distributed as the
`OpenAI.Codex` Microsoft Store package and displayed as ChatGPT/Codex. It does
not cover Codex on the web, which runs on OpenAI infrastructure and cannot read
local provider configuration.

The switcher exists because editing `%USERPROFILE%\.codex\config.toml` while
the App is running is not a safe procedure. The App owns the directory, updates
its plugin and MCP state, and rewrites the file. A provider block inserted into
an in-memory configuration the App has already loaded can disappear at the next
rewrite. The supported workflow is therefore a transaction around an App
restart: validate, close, back up, update, launch, and retain recovery state.

## 1. What the switch changes

Nexus mode selects one capability and the custom provider:

```toml
model = "code"
model_provider = "rcsl"

[model_providers.rcsl]
name = "RCSL AI Nexus"
base_url = "https://llmapi.rcsl.online/v1"
env_key = "RCSL_API_KEY"
wire_api = "responses"
```

`model` is a Nexus capability, not the backing Ollama or MLX model. Routing on
the server decides which registered model serves `code`.

The switcher passes `RCSL_API_KEY` only to the new App process. It does not use
`setx`, modify the user or machine environment, write the key into TOML, or
replace ChatGPT authentication. The Nexus key authenticates the custom model
provider; it is not an OpenAI API key and not a ChatGPT session.

OpenAI mode restores the top-level `model` and `model_provider` lines captured
before Nexus mode and starts the App with no process-scoped Nexus key. It does
not run `codex logout`, delete `auth.json`, sign out of ChatGPT, remove plugins,
or reset App state.

The `[model_providers.rcsl]` table is intentionally retained while inactive.
App tasks created in Nexus mode may continue to name that provider. Removing
the definition can make the App fail while reopening one of those tasks even
though new tasks should use OpenAI.

## 2. Requirements

- Windows 10 or Windows 11.
- Windows PowerShell 5.1 or later.
- An RCSL AI Nexus key scoped to `code`.
- Network access to `https://llmapi.rcsl.online`.
- `winget` and Microsoft Store access only if Codex App is not installed.

The switcher discovers the App by the `OpenAI.Codex` AppX identity. If AppX
discovery is unavailable, it derives the package root from the `codex.exe`
execution alias. Package installation paths contain the App version and must
never be hard-coded.

When installation is required, the switcher runs the command documented for
the Windows App:

```powershell
winget install --id 9PLM9XGG6VKS --source msstore `
  --accept-package-agreements --accept-source-agreements
```

Installation can still require Microsoft Store availability or organizational
approval. A successful `winget` exit is followed by package rediscovery; it is
not treated as proof by itself.

## 3. Start the GUI

From the repository root:

```powershell
powershell.exe -NoProfile -STA -ExecutionPolicy Bypass `
  -File .\scripts\windows\codex-app\Start-CodexAppSwitcher.ps1
```

The GUI shows the detected App version, whether it is running, the effective
top-level provider selection, and whether a persistent legacy
`RCSL_API_KEY` exists.

`ExecutionPolicy Bypass` applies only to that PowerShell process. The script
does not change the machine or user execution policy.

## 4. Connect the App to Nexus

1. Finish, cancel, or hand off every active App task. Provider changes are not
   safe while work is running.
2. Enter the gateway base URL. Leave the production default unchanged unless
   an operator has supplied another deployment.
3. Enter `code` as the capability unless the issued key and routing policy are
   explicitly for another agent-capable capability.
4. Paste the Nexus API key into the masked field.
5. Leave **Validate GET /v1/models before changing the App** enabled.
6. Select **Connect App to RCSL AI Nexus**.

The switcher then performs these operations in order:

1. Discover or install the App.
2. Validate the key against `GET /v1/models` and require the selected
   capability in the response.
3. Ask all ChatGPT App windows to close normally.
4. Refuse to continue if any App process remains after the timeout.
5. Copy the exact pre-switch configuration under
   `%LOCALAPPDATA%\RCSL-AI-Nexus\codex-app-switcher\backups`.
6. Record the original top-level model/provider lines in a secret-free state
   document.
7. Update the selection and RCSL provider definition with an atomic file move.
8. Start `ChatGPT.exe` directly with a process-scoped `RCSL_API_KEY`.
9. Restore the launcher's own process environment immediately.

The App and its child app-server inherit the key; later terminals, unrelated
applications, and a normally launched App do not.

The App and CLI share the selected `config.toml`. While Nexus mode is active, a
separately launched CLI also sees `model_provider = "rcsl"` but does not inherit
the GUI's key. Either give that CLI process its own `RCSL_API_KEY` or restore
OpenAI before using it. The switcher does not install or operate the npm CLI.

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

If no switcher state exists, recovery is deliberately narrow: the tool removes
only an exact top-level `model_provider = "rcsl"` and exact
`model = "code"`. It does not guess what a previous model was and never
restores a whole stale backup over newer App-managed plugin or MCP changes.

After restoration, create a new task and confirm the expected OpenAI model is
available. Do not use the continued existence of the inactive RCSL provider
table as a mode signal; the selected top-level provider is the signal.

## 6. Run the doctor

Local, read-only checks:

```powershell
powershell.exe -NoProfile -File `
  .\scripts\windows\codex-app\Test-CodexAppConnection.ps1
```

Add DNS, TLS, unauthenticated health, and authenticated model-catalogue checks:

```powershell
powershell.exe -NoProfile -File `
  .\scripts\windows\codex-app\Test-CodexAppConnection.ps1 `
  -Online -Authenticated
```

The key prompt hides input. There is intentionally no API-key parameter: a
command-line secret is observable in process listings and likely to be retained
in shell history.

The doctor reports:

- Windows support;
- package identity, version, and discovery method;
- App process state;
- `config.toml` path and selected model/provider;
- RCSL provider presence;
- recovery-state and backup availability;
- legacy user- or machine-level key presence, without reading the value;
- DNS, TLS, and `/healthz` when `-Online` is used;
- authenticated `/v1/models` capability visibility when `-Authenticated` is
  used.

`-AsJson` emits machine-readable results and exits non-zero if any check is
`FAIL`.

## 7. What the doctor cannot prove

An HTTP check can prove the network, perimeter, key, capability, and routing
catalogue. It cannot prove the desktop App-specific agent loop. The App may add:

- plugins and MCP tools;
- hundreds of tool definitions resent on every turn;
- hidden model slots such as automatic review;
- a model picker that overrides the configured model;
- behavior changed by a self-update since the last measured build.

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
| App is still running | The normal close path did not finish. Resolve active work and exit from the App or tray; the tool will not force-kill it. |
| App is absent and winget is unavailable | Install Microsoft App Installer or use the Store manually, then retry. |
| `GET /v1/models` returns 401 | The key is wrong, expired, revoked, or outside its CIDR. The public response deliberately does not distinguish them. |
| `code` is absent from `/v1/models` | The key does not hold that capability or no routable policy is visible to it. Do not change the App yet. |
| `403 capability_not_issued` names an OpenAI model | The App picker or a hidden slot overrode `model = "code"`. Inspect the exact refused name before changing permissions. |
| `413 context_too_long` on a new task | App-injected tool definitions may dominate the prompt. Starting another task will not reduce a tool list resent on every turn. |
| App reopens an old task with a missing provider | Preserve `[model_providers.rcsl]`, then start a new task. Do not delete global state or authentication. |
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

`state.json` contains paths, mode, hashes, original model/provider lines, App
version, URL, and capability. It never contains the Nexus key or ChatGPT
credentials.

If manual recovery is necessary:

1. Exit Codex App completely.
2. Copy the current `config.toml` aside with a timestamp.
3. Read `state.json` and the named backup; do not assume the newest-looking file
   is the pre-switch side of the transaction.
4. Prefer restoring only `model` and `model_provider`.
5. Preserve `[model_providers.rcsl]` while any Nexus task remains.
6. Never delete `auth.json`, `.codex-global-state.json`, sessions, or
   conversations as a provider-switch recovery step.

Revoking the key in the Nexus management UI is the only server-side disconnect.
Removing configuration from one Windows machine does not invalidate copies of
the key or configuration elsewhere.
