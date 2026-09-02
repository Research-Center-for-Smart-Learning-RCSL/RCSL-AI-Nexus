# Progress Log

What has actually been built, in the order it happened, and what was learned
doing it. Newest first.

This is the narrative record. Two other places describe state and neither
replaces this one:

- [`ROADMAP.md`](./ROADMAP.md) is the plan, item by item.
- [`architecture/security.md`](./architecture/security.md) section 13.0 is a
  checked control-by-control inventory of what exists.

If those two disagree with this file, they are wrong: update them here first
and propagate. The reason for saying so is that they have already drifted once.

## How this is arranged

**One file per day, under [`progress/`](./progress/), named by its date.** This
page is the index and holds no record of its own.

It was a single file until 2026-08-30, and by then it was 744 KB across 12,320
lines — long enough that a summary block had been added *because* nothing else
answered "what is the state of this, right now", and long enough that the
summary then went stale and was found to contain ten false sentences. Splitting
it is the fix for the thing the summary was compensating for. Citations
elsewhere in the repository name a date rather than a heading — "PROGRESS.md
2026-08-07" — so a file per day is the unit they were already using, and no link
anywhere depended on a heading anchor.

A day that carried several separate pieces of work carries them as sections
inside its file. The three undated blocks that used to sit in the log were
never log entries at all; they are point-in-time snapshots and are listed
separately at the end, marked as superseded.

## The log

### September 2026

**[2026-09-02](./progress/2026-09-02.md)**
- The deployment had moved away from the documents, and the harness written to protect it had gone stale in exactly the way its own comment predicted
- Upgrading the runtime, and the two gigabytes it quietly took
- The bench, and two ways it was measuring itself before it measured anything
- What a full-context request actually costs, and the guardrail it has already outgrown
- Qwen 3.8 27B, measured

### August 2026

**[2026-08-30](./progress/2026-08-30.md)**
- The deploy, and a credential helper that has now stopped one
- Ten review findings, and the two that were about a promise rather than a line
- The platform now hands over the tools it tells people to run

**[2026-08-29](./progress/2026-08-29.md)**
- A review of the day's own work found four more, and one of them was the lesson the day had already learned
- The App task ran, and the process that ran it was one the switcher could not see
- Running the switcher against the real App settled two hypotheses and refuted a third
- The Windows switcher had never been run, and four separate faults were each enough to prove it

**[2026-08-28](./progress/2026-08-28.md)**
- The landing page deployed, and a credential helper that is still broken three days later
- The review pass on the landing branch: one untested join, one door that needed no scripting

**[2026-08-27](./progress/2026-08-27.md)**
- A public front door, and two entry curtains that cannot hold the application hostage

**[2026-08-25](./progress/2026-08-25.md)**
- The Windows App connection became a reversible operation instead of a remembered edit
- Issuing defaults raised, the expiry ceiling moved to ten years, and a deploy that spent an hour on a credential helper rather than a network
- The build failed for an hour, and every layer it appeared to implicate was healthy
- Restarting Docker Desktop is a third path the reconciler does not cover

**[2026-08-21](./progress/2026-08-21.md)**
- A frontend pass, and a deploy that shipped the defect it was written to fix

**[2026-08-20](./progress/2026-08-20.md)**
- Oversized modules separated without changing the edges

**[2026-08-18](./progress/2026-08-18.md)**
- The runtime changed accounts, one model did not come back, and the capability that needed it was the one thing that could not ask for it
- Committing by path did not keep two sessions apart, because staging is per file
- The download path verifies digests now, and the library everyone assumes does this does not
- Four the morning's audit named and left open, and one of them turned out not to be a disagreement at all
- Ollama came off the operator's admin login, and the reason it had never moved was a directory mode
- A review of the hour-old refusals filters, and the completion the screen offered matched a column that never contains it
- A key may now stop refusing the model name its client insists on sending, and the argument was about what that costs
- Three things the refusals screen could not be asked, one of which the backend had been able to answer all along
- The claim that a desktop app makes a machine unconnectable, refuted by the machine that had been connected all along
- The state file an operator was told to delete held nothing it was said to hold
- An integrator's unrelated problem arrived addressed to this platform, and the evidence was cheap
- Adding a retention dataset broke the Retention screen, and the mirror is why
- A page of other people's refusals did not say whose
- The Refusals table could be widened, and stretched, by its own content
- A review of the two features found seven things, and all seven were real
- The Refusals screen copies as Markdown, and three older copy buttons got fixed on the way
- Deployed, and the deployment found a defect no test would have
- A caller can read their own refusals now, and an administrator anyone's
- Prompts are counted with the model's own vocabulary now, and it is exact

**[2026-08-17](./progress/2026-08-17.md)**
- Every refusal this platform can produce, sorted by what it tells the caller
- The estimator, measured against the tokeniser on the payloads that were refused
- The fix sat undeployed for five hours while the incident it fixed repeated
- The capability the truncation rule was actually protecting was `assist`
- A client that could not send an empty conversation, and a slug recorded wrongly
- The key that would not save, and why it looked like the wrong field
- The evaluation is a screen now, and the caveats are stored with the numbers
- The importer resolves an administrator rather than writing to Postgres
- The first import was five points wrong, and the table looked fine
- And the fabrication finding reached a user-facing screen

**[2026-08-16](./progress/2026-08-16.md)**
- `code` and `chat` both moved to `qwen36-35b-a3b-q8`, and the control plane could not be reached from the machine it runs on
- The ten-rung harness on the new `code` policy: nine passes, and the tenth is the one that matters
- Minting the harness key found a control that is actually in force

**[2026-08-15](./progress/2026-08-15.md)**
- The sixteen-task set ran, and it separates the candidates the twelve-task set could not
- The calibration gate failed twice, and it was the task set that was wrong
- A prompt's formatting was measured and reported as a model's capability
- Every candidate fabricates rather than refusing, and nothing else here would show it
- What the run does not settle

**[2026-08-14](./progress/2026-08-14.md)**
- The context ceiling was enforced in the wrong unit, and two harder limits sat above it unrecorded
- A user reported eleven characters, and all four defects were in what the platform said rather than in what it did
- Measured while diagnosing the above: the quota charges for work the machine does not do
- What that does to yesterday's entry, which merged the day before this one
- Oversubscription, measured on a real model instead of derived
- The candidate worth switching to does not use the SSD at all
- Capability: three models, and no measurement here tells them apart
- The 2026-08-07 table cannot be compared against, and this is why
- Not measured, and what each would take

**[2026-08-13](./progress/2026-08-13.md)**
- Buying a stronger model with the SSD: the exchange rate, and the two conditions on it

**[2026-08-10](./progress/2026-08-10.md)**
- The browser now reaches the gateway, and the join was the whole point
- The audit action list is generated now, and one of its call sites was a trap

**[2026-08-09](./progress/2026-08-09.md)**
- An operator's own Codex session found three things the verification missed
- The nginx timeout, and deriving a number instead of reading it
- Two documentation failures of the same kind, in opposite directions

**[2026-08-08](./progress/2026-08-08.md)**
- The prompt log that section 9.2 described for four months
- The retention bound points the other way, and the code had one shape for it
- The gateway may write this table and may not read it
- Listing and reading are two different requests, and only one is audited
- The scope was placed wrong first, and a test that predates it said so
- Two things found rather than added
- State
- CI had been red for five commits and every document said it was green
- Deployed and verified the same day

**[2026-08-07](./progress/2026-08-07.md)**
- The public entrance passes under its new names
- The probe meant to settle a checkbox found an ordering defect
- The ceiling, and what FastAPI did to the first version of it
- Deployed, and the live re-run
- The verification found a second, older defect: uploads above 10 MB have never worked
- Two smaller things the same afternoon turned up
- The wiring tail is 19 minutes, measured twice
- The main model is now gemma4:31b-it-qat, and switching it found two defects
- The agent client cannot connect yet, and the check that should have said so passed
- The runbook told integrators to set a field removed six months earlier
- `/v1/responses`, scoped from a recording rather than a specification
- The documentation caught up, and a screen was added for the person doing it
- Whether the assistant should run on gemma4-31b: measured, and no
- The main model moved to q8, and the measurement that justified it found nothing

**[2026-08-05](./progress/2026-08-05.md)**
- Where the memory went, and whether the SSD can take some of it — OPEN
- Prompt templates, and the feature defined by what it does not do
- Review of the day's work: seven findings, all real
- The frontend and the backend can no longer drift quietly
- A local model does drive an agent loop, and deliberation costs 42% of the wall clock
- The harness I told you to reproduce with could not run
- The `code` policy exists, and the client does not have to know
- The unverified MLX tool path is now refused, not merely warned about
- The debug switch had a reader and no writer on the user half
- The deploy that reported success and shipped nothing
- The two things the deploy walked past, both now closed
- The gateway can call tools, which is what "OpenAI-compatible" was missing
- Frame order is the same lesson for the third time
- Four documented absences became behaviours, and the page said the opposite
- Deliberation is per capability now, because an agent pays for it every turn
- The context ceiling moved, and it could not move alone
- Review of the tool calling commit, and its four fixes
- What is not proven
- A second review, this time against the running runtime
- Error precision: the id that was promised, the codes that were one code

**[2026-08-04](./progress/2026-08-04.md)**
- Records now have an expiry date, and an administrator can bring it forward
- The entrance is green on both new names
- What grows without a bound, and the one thing that already had
- One symptom, two causes, and neither was the width someone had set
- The last key was revoked, and the list it left behind needed a filter
- Redeployed, and the build refused for a file it had never been given
- A scope nobody could spend, and the nav that had no test
- Both runtime advisories are closed, and one of them was called unfixable twice
- The public hostnames became single-label, which is a certificate decision
- A review found three serious defects in the day's work, two of them mine
- The account screen answers "why can I not see that screen"
- Four more roles, and a UI that says what they mean
- The Users screen could not edit a user, and both reports were the same gap
- The four findings from the sweep, all addressed
- A sweep of the whole platform, now that there is a way in to sweep it with
- Two defects in the second step of sign-in, and neither was reachable until today
- The entrance passes everything, and the defect underneath it was waiting
- A 401 from the public entrance said the tailnet had dropped
- The entrance came back with the headers still missing, and the 400 is not the page
- Why a correct configuration is not the loaded one
- The entrance is off, and the script blamed the certificates
- One probe, four causes, and a confident message for the wrong one
- A "postcss and sharp, upstream and unfixable" advisory turned out to be one of them

**[2026-08-03](./progress/2026-08-03.md)**
- The public entrance went live, and two controls were reporting nothing
- The perimeter had an explanation for all of it, and threw it away
- The configuration was correct, and correct in the wrong place
- Deployed, and the log immediately said what the probing had inferred
- An acceptance script, because neither failure shows up in a status code
- The deploy, and a page whose own HTML could not confirm it
- The country database stopped ageing, four days after the mechanism to stop it existed
- The five gaps in `/api-docs`, and the two the audit itself had got wrong
- The review, which found the same defect this entry had just claimed to avoid

**[2026-08-02](./progress/2026-08-02.md)**
- The administrator got public-entrance credentials, and the last two events fired
- Two scripts that were wrong, and the second was wrong in the worse way
- Deployed and verified on the Mac Studio the same night
- Two completeness sweeps, one of which came back clean and one of which did not
- A sentence in security.md that had been describing an intention for months
- What was built, and the two defects the building turned up
- Where the checks were put, and what putting them back proved
- The review of this work, and the amplifier the fix had built
- And the logs screen's Failure filter had never matched a row
- What was deliberately not done

### July 2026

**[2026-07-30](./progress/2026-07-30.md)**
- What `/api-docs` does not say, audited against the wire it describes
- Review of the day's four commits, and the six things it found
- The first CI this repository has had, and what it found in its first run
- Re-index without re-upload, and a preview that shows the text rather than the file
- The registry stops taking its own word for it (Phase 2)

**[2026-07-29](./progress/2026-07-29.md)**
- An assistant in the admin UI, and the one filter that would have defeated it
- The filter that had to be re-applied by hand
- A setting nothing read
- What the assistant is not allowed to be slow
- Reading past the terminator
- Deployed, and the two prerequisites that were not remote after all
- What the review found, and the one it was wrong about
- Removing each fix to see whether its test notices
- The keychain again, from the other side, with a push that looked like it failed

**[2026-07-28](./progress/2026-07-28.md)**
- The key was issuable and unusable
- The capability list on a key was decoration
- Smaller things found on the way
- What review found in the same day's work
- The documentation audit that followed, and the two claims that had rotted
- What is still not done

**[2026-07-27](./progress/2026-07-27.md)**
- A generation that answered nothing looked identical to a malfunction
- The Docker build was blocked by a locked keychain, not by Docker
- Auditing the documents found four things that were already wrong
- Ollama's five-minute timer had been overruling the registry all day
- The wait before the reasoning appears was drawn as nothing at all
- Review found two live defects, and one hypothesis worth writing down as refuted
- The first thinking model went in, and three layers written for non-thinking models all failed at once
- Thinking became a per-request choice, after four attempts to make the model converge failed
- Deploying that fix cost a Docker Desktop restart, and the restart proved the 2026-07-26 failure repeats
- The fix, measured against the failure it was written for
- A Claude Code session left running through screen-off was reachable again over a remote login, memory intact

**[2026-07-26](./progress/2026-07-26.md)**
- Auditing "can this be run entirely remotely" found one real hole and one contradiction between two files
- The container bring-up path ran 51 seconds into the boot, and that same boot falsified a number the reboot argument rested on
- The second repair path turned out to be injectable too, and the claim that it was not was mine
- The injected boot filled the row seven boots could not, and settled two things the last entry left open
- Two more boots proved the lever cannot work, and the liveness record had a hole where it is read
- The fifth boot passed and proved nothing, and the two checks written that day could each only say yes
- Round two, the OS update: nothing brought the containers back, and the reconciler called that a success
- The third boot: the last unproven link, and the diagnosis that did not survive it
- Something now watches the state nothing was watching, and what it still cannot see
- Round one passed, and the margin it passed by turned out to be measurable
- The reboot test, which the chain failed in the one way nobody would notice
- Grafana's host port had never bound, and the reboot only made it visible
- FileVault deferred, and the headless prerequisites the runbook was missing
- FileVault off, and the unattended-recovery chain that is built but not yet proven
- Remote access, and a diagnostic that invented the wrong conclusion
- Inference served end to end, and a model that could never leave its initial state
- The stack is up on the Mac Studio, and the frontend could not reach its backend
- The tailnet ACL, which the runbook never told anyone to apply
- GPU inference, verified at last, and two runbook steps that were quietly wrong
- The Mac Studio exists, and a test that had stopped testing anything

**[2026-07-25](./progress/2026-07-25.md)**
- Logs UI and usage charts, and a chart library chosen by not choosing one (Phase 2)
- Observability: the emission side, and the word "metrics" pulled apart (Phase 2)
- mypy made honest, and put where it cannot drift again
- The last resource guardrail: a wall-clock generation deadline
- Multi-tenancy, the isolation boundary made real (Phase 2)
- Node management, and the SSRF guard that had to ship with it (Phase 2)
- The second runtime adapter, which is the real test of the layering (Phase 2)
- A production smoke test on the dev machine, which moved the deploy risk down
- A first-deploy runbook, and the GeoLite2 mount it turned up
- The database account split, and secrets moved to file mounts
- A routing policy editor, so the one thing that makes the gateway serve is no longer curl-only
- A frontend test runner, on the units where a defect is a security defect
- Closed the network exposure the review left standing
- Five adversarial reviews, and the twenty-eight defects they found
- The rest of the admin API

**[2026-07-24](./progress/2026-07-24.md)**
- Admin authentication, end to end
- Theme and progress tracking
- Everything the adversarial review found, fixed
- Guardrails that were configured but never read
- Phase 1 backend, end to end
- Scaffold
- Licence: AGPL-3.0
- The public entrance, and the risks accepted with it
- Architecture documents

## Snapshots

Written at a moment and kept as written. Not maintained, and superseded by
[`ROADMAP.md`](./ROADMAP.md) and [`architecture/security.md`](./architecture/security.md)
§13.0. They are here because they are part of the record, not because they
describe the platform now.

- **[Current state](./progress/2026-08-18-current-state.md)** — written 2026-08-18

- **[What comes next](./progress/2026-07-26-what-comes-next.md)** — written 2026-07-26

- **[Where things stand](./progress/2026-07-24-where-things-stand.md)** — written 2026-07-24
