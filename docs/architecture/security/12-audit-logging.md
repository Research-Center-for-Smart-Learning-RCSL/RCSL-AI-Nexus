# 12. Audit Logging

[← Security Architecture and Threat Model](../security.md)

**Events that must be recorded** (who, when, what, from where, and the outcome), and where each stands as of 2026-08-02:

| Event | State |
|---|---|
| Management sign-in and sign-out, including failed attempts | `user.signed_in`, `user.sign_in_failed`, `user.sign_in_throttled` (once per address per window), `user.signed_out` (§5.3). **Public entrance only, because it is the only one with a sign-in**: the tailnet entrance resolves an identity per request from a header and has no session to begin or end, so there is no event to record there. A tailnet caller with no account is a 401 and appears in the application log. One second-step refusal is unrecorded and named in the code: a challenge whose user id no longer exists has no subject, and inventing one would put a fiction in the log for an investigation to rule out |
| **First-administrator bootstrap** (§5.5) | `bootstrap.first_admin` |
| Invitation and reset link issue and consumption | `user.invited`, `user.invitation_reissued`, `user.invitation_accepted`, `user.password_reset_issued`, `user.password_reset_consumed` |
| TOTP enrolment | `user.totp_enrolled` at acceptance, `user.totp_reenrolled` later in an account's life |
| Recovery code use | `user.recovery_code_used`, its own row beside the sign-in: spending a single-use credential is a fact about the account, not about that login |
| API key issuance, modification, revocation | `api_key.issued`, `api_key.updated`, `api_key.revoked` |
| **Transcripts read** (§9.2) | `prompt_log.read`, one row per conversation opened, naming its id. Added 2026-08-08 with the full-text logging it accompanies, because a control that records what somebody typed and lets it be read without recording *that* is half a control — and it is the half this document's history says goes missing. Listing transcripts deliberately writes nothing: the list carries no message content, so an event there would fire on every page refresh and describe no disclosure. The `detail` carries handles only, never a snippet, since `audit_log` keeps 360 days against this table's 7 |
| **Debug windows opened and closed** (§9.2) | `api_key.debug_window_set` and `user.debug_window_set`, one row per press including the closing one. Their own event class rather than an `updated`, on both credentials, because what they change is what the platform *reveals* rather than what the holder may do — so the record of who widened the disclosure sits beside the record of what was then disclosed. Added 2026-08-05, after this table's 2026-08-02 survey |
| Model download, load, unload | `model.download_started`, `model.loaded`, `model.unloaded`, each with a `failed` outcome as well; plus `model.registered`, `model.updated`, `model.deleted` |
| Routing policy changes | `routing_policy.saved`, `routing_policy.deleted` |
| Node registration and removal | `node.registered`, `node.updated`, `node.removed` |
| User role changes | `user.role_changed`, plus `user.updated`, `user.disabled`, `user.enabled`, `user.deleted` |
| Knowledge base uploads, deletions, collection lifecycle | `knowledge.document_uploaded`, `knowledge.document_deleted`, `knowledge.collection_created`, `knowledge.collection_deleted` |
| **Prompt template authoring** (§7.4) | `prompt_template.created`, `prompt_template.updated`, `prompt_template.deleted`. A template is the one message the model treats as authoritative and every answer that selects it is shaped by it, so who changed it is the same class of question as who changed routing |
| **Retention policy and purge** (§12.1) | `retention.policy_set` and `retention.purged`. The second is the row that a subsequent purge of `audit_log` can itself remove, which is the whole of what §12.1 is about — it is recorded like any other administrative action and is not protected from the power it records |
| **Tenant creation** (§7.3) | `tenant.created`. The boundary every other authority is confined by, and `tenant:write` is one of the three scopes in `ADMIN_ONLY_SCOPES` for that reason |
| **Password change and step-up refusal** | `user.password_changed` when somebody replaces their own password (which also ends every other session for that user), and `user.password_verified` with `outcome="denied"` from the shared `_verify_current_password` that guards both a password change and a TOTP re-enrolment. Only the denial is recorded there: a successful step-up is followed by the event that needed it, and a failed one is somebody at a keyboard who could not produce the password for an account they are already signed in to |
| **Evaluations imported and deleted** | `evaluation.imported`, `evaluation.deleted`. Audited although a run changes no configuration and grants nobody anything, because what it does change is the evidence a later routing decision cites — and an import replaces any earlier run carrying the same label, so this is the only record that the numbers on that screen were once different |
| **Refusals read across accounts** (§9.5) | `refusal.read_any`, one row per request that reaches for somebody else's refusals, naming whose — and, since 2026-08-18, naming the name searched for where the reader asked by name rather than by id. A name is the *broader* of the two reaches, since it describes a set the searcher did not have to know the members of, so recording only the id would have left the wider read as the unlogged one. Reading one's own writes nothing: that is the feature working as designed and a row per screen refresh would be the noise `prompt_log.list` was denied for. What is recorded is a reader reaching across accounts, because a month of somebody's 413s describes how they work even though it contains nothing they typed |
| Authorization failures | `authz.denied`, recorded in the shared exception handler (`interfaces/http/errors/handlers.py`) rather than in `AuthorizationPort.require`, so no use case can forget and refusals raised directly — an administrator changing their own role, a key that does not exist — are caught too. **Admin entrances only; see below** |
| Alerting on repeated failures | **Not built.** `user.sign_in_throttled` and `authz.denied` are the rows a rule would query; the rule is a §13 Phase 3 item |

**Nine of the twenty-one classes above have been observed on the deployment, not just implemented, and that survey is from 2026-08-02.** (Fourteen classes were listed until 2026-08-08, when transcript reads joined them, and fifteen until 2026-08-18, when refusals read across accounts did. Neither of those two has rows in the table yet, for the same kind of reason as the three named below: nobody has opened a debug window on this deployment, and nobody has yet read somebody else's refusals through the screen rather than through a script. **The last five classes — prompt templates, retention, tenants, password changes and evaluations — were added to this table on 2026-08-18, when it was audited against `AuditAction` and found to be missing them.** Every one of those events was already being written by a shipped feature; what was missing was the row. They postdate the survey entirely, so nothing here says whether any of them has fired, and the honest count against today's table is nine of twenty-one rather than nine of sixteen.) As of 2026-08-02 the live `audit_log` holds rows for sign-in, sign-out, failed attempts, the limiter firing, bootstrap, invitation reissue and acceptance, TOTP enrolment, API key issuance, model download/load/unload, routing policy saves, all four knowledge-base actions, and authorization refusals. The three with no rows — **recovery code use, node registration, and user role changes** — are absent because those actions have never been performed here: one user, so no role to change; a single node written by `provision` rather than through the write endpoint; and no reason to spend one of ten recovery codes to watch a row appear. That is a different thing from a recording that does not work, and keeping the two apart is the point of this list: this document's own history is of controls that were designed, written down, marked done, and not actually in force.

### 12.1 The Audit Log Is Deletable, and by Whom

Since 2026-08-04 a `retention:write` holder can set how long audit entries are
kept and can purge them ahead of that (§12 events still record as before; this
is about how long the rows survive). The default is 360 days.

**This weakens the audit log, deliberately and with the alternative on the
table.** The rejected design kept the purge but wrote a record of each one that
no later purge could remove. What is implemented instead is the fully open
version: `retention.purged` is recorded like any other administrative action,
and a subsequent purge of `audit_log` removes that record too. The consequence
is exact and worth stating plainly: **a platform administrator can erase the
evidence of what they did.** The log defends against a compromised gateway, a
confused operator, and a dispute about what happened — not against the person
holding `retention:write`.

Three things bound it. `retention:write` is in `ADMIN_ONLY_SCOPES`, so a
`tenant_admin` cannot erase their own trail inside the tenant they administer,
which is the case this would otherwise have created. The floor is 30 days, so a
standing policy cannot be set to something that forgets faster than an incident
is usually reported. And the dataset is a closed enum reaching the delete, so
"purge" can never be pointed at `users` or `api_keys`.

What would restore the property, if it is ever wanted: ship audit rows off the
machine as they are written — a syslog sink or an append-only bucket — so that
deleting the table locally stops being the same as deleting the record. That is
a Phase 3 item and is not built.

**The gateway does not write audit rows, and that is a decision rather than an omission.** Its database account may INSERT into `usage_records`, `prompt_logs` and `refusals`, and nothing else — and it may not `SELECT` the last two (§6). Granting it `audit_log` would let a compromised gateway write into the record that exists to describe the compromise, which is a poor trade for capturing one event: a key reaching for a capability it was not issued for. That refusal is a 403 in the application log and in the usage series, and it is the one item on this list the audit log does not hold. The three tables it may write are all append-only records of its own traffic, two of which it cannot read back — which is a shape `audit_log` would not have, since the value of that table is that it is written by a wider authority than the one being recorded.

**A value that does not fit is trimmed, not dropped.** Postgres refuses an over-long string rather than truncating it, and `PostgresAudit.record` swallows its own failures so that a failed audit write cannot turn a successful action into a 500. Those two together mean an unbounded value silently loses the event — and `target` on an authorization failure is the request path, which nothing bounds. The writer trims to each column's width with a marker, so padding a URL cannot suppress the record of someone probing.

The audit log is stored separately from application logs and designed append-only. **Its retention is 360 days by default with a floor of 30**, both settable by a `retention:write` holder — which is not "at least a year", as this line said until 2026-08-18, and the difference is the whole of §12.1 above: the default is a year-ish, the guarantee is a month, and the guarantee is the number an incident response can rely on. 360 rather than 365 is the value as given and nothing depends on it being either. After any incident this table is the only thing that can answer what was actually accessed, which is why the floor exists at all: a week of history is too little to investigate anything reported late.
