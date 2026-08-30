# 9. Data Protection and Logging Boundaries

[← Security Architecture and Threat Model](../security.md)

### 9.1 Classification

| Data | Sensitivity | Handling |
|---|---|---|
| Model weights | Low | No encryption needed |
| Knowledge base documents | **High** (unpublished research) | Encrypted backups, access auditing |
| Prompts and completions | **Highest** | Not persisted by default, see below |
| Prompt transcripts (`prompt_logs`) | **Highest** | Written only while a credential's debug window is open; retention is a **ceiling** of 30 days on a default of 7; the gateway writes and may not read; reading one is audited (§9.2) |
| API key digests | High | HMAC with pepper |
| Audit log | Medium | Append-only, stored separately |
| Refusals | Medium | Append-only; what the platform told a caller, never what they sent (§9.5) |
| Usage records | Medium | Metadata only — actor, capability, model, token counts, latency. The one dataset here the gateway both writes and reads, because quota enforcement is a gateway decision |
| Evaluation runs | Low | Benchmark scores about the fleet's own models, no tenant scope and no caller content. Written under `model:write` and read under `model:read` on the admin entrances only; import and deletion are audited |

The first table in this document to describe a dataset that did not yet exist would be a failure of the kind §13.0 is about; the failure this table actually had, until 2026-08-18, was the opposite — three of the datasets above had shipped and had no row, so the classification was complete about the schema of an earlier month.

### 9.2 Logging Boundaries

Prompt content is the most sensitive data here, because researchers type unpublished ideas directly into it.

**Metadata only by default.**

| Logged by default | Never logged by default |
|---|---|
| request id, timestamp | message content |
| `key_id` or user login, owner | completion content |
| capability, model actually used | retrieved knowledge base passages |
| token counts, latency, status, error class | |

When full logging is genuinely needed for debugging, it is enabled by an **expiring** switch: `debug_logging_until` on the API key **and on the user record** (the management chat path has no API key attached). Full-text retention is configured separately and is markedly shorter than ordinary log retention. The expiry exists to prevent the common ending where full logging is enabled for an afternoon and left on for a year.

**What the switch does, as of 2026-08-08 — two things now, not one.** While the window is open, error responses to that credential carry `error.detail` (the **only** way `detail` itself ever leaves the process, §5 and `interfaces/http/errors/details.py`; every other exception to "no internal detail in responses" is a named *figure* rather than the detail string, and six error classes carry one rather than the two this line counted on 2026-08-17), **and the platform records the full prompt and completion text of every request that credential makes**. One hour per press, capped at 24 by the backend, closing by itself, and audited because it loosens an information control. The second use is the one this section described from the first draft and nothing implemented until 2026-08-08; the switch existed from the first migration and was consumed by nothing at all until the error-detail use landed on 2026-08-05. The two rows of the metadata table were likewise aspirational on one point — `request id` is logged *and returned* (header `X-Request-Id`, `error.request_id`) only since the same date.

**The figures are narrower than the switch and rest on a stated test.** The two
that prompted the test were added 2026-08-17 and 2026-08-18, after two operators
each lost an evening to a refusal that was correct, permanent, and silent about
which of the things they had just changed had caused it: `ContextTooLongError`
carries `estimated`, `limit`, `composition` and `basis`, and `ApiKeyLifetimeError`
carries `maximum_days`. **A figure may reach a caller when it describes the
caller's own payload back to them, or when it is a policy this deployment
publishes; it may not when it describes the inventory.** That is why `limit` was
weighed rather than assumed harmless — on a fallback it is half a specific
model's registered context — and why the model's alias is still withheld and
`detail` still does not leave the process. Unlike the switch above, none of them
is time-boxed or audited, because none discloses anything the caller did not
send or could not read in this documentation.

**`public_details` is where the whole set lives: six error classes and one
cross-cutting rule, not two exceptions.** One function, because there are two
readers that must not disagree — the response body renders it and `refusals`
stores it (§9.5). Besides the two above
it returns `capability` and `available` on `CapabilityNotIssuedError` (the
caller's own key and the list `GET /v1/models` would hand them anyway), `reason`
on `WeakPasswordError` and on `UploadRejectedError` (the caller's own password
and the caller's own file — an operator told only "this file cannot be accepted"
cannot tell a size limit from a type one), `retry_after_seconds` wherever an
error carries one (a published policy, and the figure a caller reading their own
refusals a day later has no header for), and `required_gb` / `available_gb` on
`InsufficientMemoryError`. **The memory one is the exception to the rule stated
above and is worth naming rather than counting**: it describes the inventory, not
the caller's payload. It is tolerated because it is an admin-entrance refusal
behind `model:write` — the caller being told the machine's memory is the person
administering the machine — and it would not be tolerable on the gateway. The
rule is what makes that visible; a count of "three" was what hid it.

`basis` is the field that says which of three things produced `estimated`:
`tokenizer` when the model's own vocabulary and chat template counted it,
`estimate` for the character-width fallback, `lower_bound` for the cheap guard
that runs before a model is chosen. It is always present when `estimated` is,
because its absence would be read as "exact" by anyone who met the field on one
deployment and not another. See §13.0's row on exact token counting.

**How the full-text half works.** `domain/entities/prompt_log.py` and its table `prompt_logs`, written by `RouteChatRequest` in the same `finally` that records usage, and read only through `prompt_log:read` on the admin entrances (`ReadPromptLogs`, `routers/prompt_logs.py`). Six decisions in it are load-bearing:

- **What is recorded is the assembled prompt, not the caller's request.** A prompt template and any retrieved knowledge passages are merged into the message list *before* `RouteChatRequest` sees it, so the transcript shows what the model actually read — which is what makes "retrieved knowledge base passages" in the table above a thing this control covers rather than a thing it misses. One write point therefore serves all three entrances, `/v1/chat/completions`, `/v1/responses` and `/admin/chat`, because all three are translations onto that one use case.
- **When the window is shut, nothing is accumulated** — not accumulated and discarded. `should_capture` is consulted once, before the first chunk, and returns no buffer at all when the answer is no. That is the difference between a disclosure control being off and being on with its output thrown away, and only the first is worth claiming.
- **The window travels on `Actor`, not on the request contextvar.** `debug_detail_active()` lives in `interfaces/http/request_context` and `RouteChatRequest` is application-layer; reaching for it there would invert the dependency. Both identity resolvers and the API-key middleware already hold the row, so the field costs one assignment each.
- **The gateway may write this table and may not read it.** `GATEWAY_WRITABLE_TABLES` gains `prompt_logs`, and `GATEWAY_DENIED_READ_TABLES` revokes its `SELECT` after the blanket grant (§6). The internet-facing process appends its own transcripts and can read nobody's — the same asymmetry Qdrant's read-only gateway key makes, inverted.
- **Retention is a ceiling here, not a floor.** Seven days by default, thirty at most (§9.4 and `domain/entities/retention.py`). For `audit_log` the danger is forgetting too soon; for this the danger is exactly the ending the expiry was written to prevent, and a 360-day default would have reproduced it with an administrator who believed they had configured something.
- **Reading a transcript is audited; listing them is not.** `prompt_log.read` names the conversation and fires once per conversation actually opened. Listing discloses no message content — `list_summaries` never selects the text columns — so an event there would describe no disclosure and would fire on every page refresh. The audit row carries handles only: a snippet in its `detail` would outlive the transcript by a year in a table with 360-day retention, which is the one way this feature could quietly undo its own bound.

**Both credentials carry it, and the second was not redundant.** The API-key window is set from the API keys page and audited as `api_key.debug_window_set`; the user window is set from the Users page and audited as `user.debug_window_set`, added 2026-08-05. The parenthesis above is the reason the user half exists — the management UI authenticates by session and carries no API key — and until that date it was also the reason the sentence was **false**: `identity.py` read `user.debug_logging_until` and granted on it, `UserResponse` carried it and the Users table displayed it, while no code path anywhere could set it. An administrator debugging the admin UI itself had no credential on which a window could be opened, and nothing about the system said so. A read with no writer is the same shape as a documented absence, and harder to see: every surface reports the feature working. The ceiling now lives in `domain/services/debug_window.py` rather than on either use case, so one control on two credentials cannot become two rules; the user-side write is conditional on `disabled_at IS NULL` in the UPDATE, so a window cannot be left open on an account somebody has just shut off.

### 9.3 Encryption at Rest and the FileVault Tension

FileVault defends against the machine being physically removed, a real risk for equipment in a shared facility. It conflicts directly with unattended 24/7 operation, because unlocking the disk at boot requires someone to type a password.

The practical position:

- **Keep FileVault enabled.** Physical theft is worth defending against more than reboot convenience costs.
- **Use a UPS** so unplanned power loss is rare (already in Phase 3).
- Use `sudo fdesetup authrestart` for planned reboots, which unlocks once for the next boot.
- Accept that unplanned power loss requires one manual unlock, and write that into the operations runbook.

**Sequencing decision.** The first deployment runs with FileVault **off**, because the UPS above does not exist yet and the machine is headless: without the UPS, the manual-unlock cost is paid at every power cut rather than rarely. The position in this section is unchanged and the UPS is the trigger to act on it. Recorded with its compensating controls in §15.6.

### 9.4 Backups

- Backups contain the knowledge base and database and therefore constitute **a complete copy of the research data**, so they must be encrypted. `restic` (built-in encryption and deduplication) or `age`.
- Follow 3-2-1, but confirm that institutional policy and any collaboration agreements permit unpublished research data on third-party cloud storage.
- **Rehearse restores.** An unverified backup is not a backup.
- Model weights can be excluded (they are re-downloadable), but keep a manifest of models and versions so the environment can be reconstructed.
- **`prompt_logs` is the one table worth considering excluding**, added here with §9.2's full-text logging. Its retention ceiling is thirty days precisely so the platform does not accumulate a corpus of unpublished ideas; a backup that keeps every nightly snapshot would restore exactly that accumulation on a different disk, outliving the window by however long backups are kept. Either exclude the table or make the backup retention shorter than the dataset's, and say which — this is the kind of interaction that is obvious when written down and invisible when not. **`refusals` is the same interaction one notch weaker** (§9.5): it holds no request content, so a restored backup is not a restored corpus of ideas, but its 180-day ceiling exists because a long enough history of somebody's refusals describes how they work — and a backup older than the ceiling reinstates exactly that.

**Implemented 2026-08-18, and every question this section left open was answered rather than deferred.** `launchd/backup.sh` is the mechanism and [`runbooks/restore.md`](../../runbooks/restore.md) is the other half of it; the file headers carry the full arguments and this is the summary.

- **`prompt_logs` is excluded** — the first of the two options this section offers, because the second is not available. Its bound is a *ceiling* of 30 days on a default of 7, so "backup retention shorter than the dataset's" would mean keeping backups for under a week, which is not a backup. The argument that actually settles it is cheaper: the rows have no recovery value, since a prompt transcript exists for the length of a debugging session and nobody restoring from a disaster wants a three-week-old one. It is `--exclude-table-data` rather than `--exclude-table`, so the schema survives and the first request after a restore does not fail on a missing table.
- **`refusals` is kept, under the second option.** Backup retention is 7 daily, 4 weekly, 3 monthly, **measured at a 49-day span on 2026-08-18** against 130 synthetic daily snapshots and bounded above at roughly 92 days, because the monthly leg counts calendar months rather than 30-day windows and so oscillates through the month. The bound that matters is the upper one, and 92 is below the dataset's own 180-day ceiling. This line said "roughly 90 days" before the policy was actually run against a populated repository. It holds no request content, so it is not the §9.2 hazard; what the retention bounds is the accumulation of shape this section's own paragraph describes.
- **`secrets/` is inside the repository**, and this is the largest decision in the design. Excluding it produces something that is not a restore: `totp_encryption_key` is what every stored TOTP secret is encrypted under and `api_key_pepper` is what every key hash is peppered with, so a backup without them restores a platform where every administrator is locked out and every key is dead. The choice was therefore never safe against unsafe, it was one item kept off the machine or sixteen, and one is the number that will still be correct in a year. The cost, stated where it cannot be missed: **the repository password plus read access to the repository is the entire platform**, which is why `secrets/README.md` says that password's only copy must not live on the machine being backed up.
- **Model weights are excluded and the manifest exists**, as this section asks. It is its own snapshot at a stable path so it can be read before anything has been restored, which is the situation it is for.
- **The Qdrant index is excluded and rebuilt.** It is derived from `documents`, and `adapters/vector/qdrant_store.py` derives point ids rather than generating them, so a re-index is idempotent. The restore runbook carries the loop; the cost is every document embedded again and it is stated there rather than discovered.

**The two captures are not atomic and no ordering makes them so**, which is worth recording here because it is a property of the data model rather than of the script. `knowledge_documents` rows point at files in the `documents` volume, so a document uploaded between the two captures leaves a file with no row and one deleted between them leaves a row with no file. Uploads and deletes cut opposite ways, so the ordering only chooses which shape is the common one: the database goes first, which makes the harmless shape (an orphan file) the ordinary outcome. The remaining shape is not papered over — the restore runbook ends with a reconciliation that lists exactly the rows whose file did not come back, so a rare inconsistency arrives as a named list rather than as a document that 500s six months later. Making the window atomic means stopping the stack nightly, and a platform that stops serving every night to protect data it is not serving is a worse trade.

**What is still open.** The repository is on the internal disk and therefore shares a failure domain with the data, which is temporary and recorded at both `backup.sh` and the runbook's §1. And this is one repository, which is one leg of the 3-2-1 above. The offsite leg is deliberately not written, because it depends on the question this section already raises and nobody has answered: whether institutional policy and the collaboration agreements permit unpublished research data on third-party cloud storage. The rehearsal **has** been run, on 2026-08-18 against the live stack, and what it proved and how is in PROGRESS.md — including that the `prompt_logs` exclusion was checked against a control rather than against a table that was empty anyway, which is the only way that particular check can return more than one answer.

### 9.5 Refusals, and Why They Are Kept Where the Caller Can Read Them

Built 2026-08-18. **Two people lost an evening each on 2026-08-17 to refusals that were correct, permanent, and silent about which of several things they had just changed had caused them.** A `413` said only that the conversation was too long; the operator opened three new ones, each refused identically, because the tool definitions filling the ceiling are resent every turn. A `409` on an API key's expiry said "The model is not in a state that allows this operation" — the platform's general conflict, while the reason sat in `detail`, which does not leave the process — and was sent seven times in three minutes by somebody who concluded the capability edit beside it had failed. Both messages were fixed the same day. Neither fix helps the next error nobody has thought about, and nothing on this platform stored a refusal at all, so answering "what happened at 19:16?" meant an administrator reading container logs.

`refusals`, written from the shared exception handler and read under `refusal:read_own` or `refusal:read_all` (`domain/entities/refusal.py`, `application/use_cases/read_refusals.py`, `routers/refusals.py`). Seven decisions in it are load-bearing.

- **A row is a second copy of what the caller was already told.** The code, the status, the public message, and the caller-facing figures — built by the same function that builds the response body (`public_details` in `interfaces/http/errors/details.py`), so the two cannot disagree. `detail` is absent by construction: it is not read there at all. The model's alias is withheld exactly as it is from the response, and no request content is stored. That is what makes the whole table safe to show its own subject, which is the point of the feature.
- **The write point is the exception handler, not the inference path.** The feature was specified as a row written in the same `finally` that records usage, so one write point would serve all three entrances as `prompt_logs` does. That works for the inference path and only for it: the `409` above was an API key's expiry on the admin surface and never reaches `RouteChatRequest`. Storing every `DomainError` — plus the `500` fallback, which is the refusal with least for a caller to act on — means writing from the one place all of them already pass through.
- **Only refusals with an identified caller are kept.** An anonymous refusal has no reader, and would be a row written at whatever rate an unauthenticated client chose to provoke one. The identity-plane refusals that matter — a failed sign-in, an authorization denial, a recovery code replayed — are already recorded in `audit_log` by §12, which is the table for events about who somebody is rather than about what they sent.
- **Reading one's own is in the base scopes.** `refusal:read_own` sits beside `usage:read_own` and reaches every human role, because being told the reason for a refusal is not an administrative privilege — being unable to look it up is precisely the condition that cost two people an evening. `refusal:read_all` is granted like `usage:read_all`, to the roles that investigate load, and is deliberately **not** in `ADMIN_ONLY_SCOPES` beside `prompt_log:read`: that one reads what somebody typed, and this one reads only what the platform told them.
- **The narrowing happens in the use case, and the response says it happened.** A reader without `refusal:read_all` has the actor filter replaced with their own id rather than being refused, so clearing a filter on a screen every account is expected to open does not answer 403 — and the page carries `scoped_to_self` so the screen can say it is showing a subset instead of presenting a control that silently does nothing. **The name search added 2026-08-18 is subject to the same replacement rather than beside it**: `actor_display` matches a substring of the recorded name and is ANDed with that overwritten id, so a reader confined to their own who types a colleague's name gets an empty page rather than the colleague's refusals. It is the only filter here that is not an equality, and it exists because the id is a uuid — the screen could show whose a refusal was and could not be asked for one person's without the reader looking that uuid up somewhere else. It is also the only thing that finds a *deleted* account's refusals, whose name survives on the denormalised column and nowhere else.
- **The row carries the caller's display name, denormalised.** The same choice `audit_log` makes, and for the same reason both tables carry no foreign keys: the row must outlive the account it names, and a name resolved by joining would vanish exactly when somebody is investigating what a departed account was doing. It is shown only to a reader seeing more than their own, and every role holding `refusal:read_all` also holds `user:read`, so it discloses nothing they could not already look up.
- **Retention is a ceiling as well as a floor**: 30 days by default, 180 at most, 7 at least (`domain/entities/retention.py`). The ceiling because a year of somebody's `413`s is a description of how they work that nobody asked to have kept — the same reasoning as §9.2's, one notch weaker because no content is involved. The floor because the reader here is the person who was refused, and a Friday refusal has to survive until Monday.

The gateway writes this table and may not read it; see §6.
