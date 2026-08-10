"""Password then TOTP authentication for the public entrance.

This is a use case rather than middleware logic because it carries real
rules that deserve unit tests: enumeration resistance, TOTP replay
rejection, and the refusal to authenticate an account whose second factor
was never enrolled. See docs/architecture/security.md section 5.3.

**Every outcome is audited except one, and that is a constraint on the code
rather than an addition to it.** Section 12 requires sign-in including failed
attempts, and this is the one use case where recording an event can itself leak:
the whole point of `dummy_verify` is that an unknown login and a wrong password
take comparable time, and an audit write is a database round trip. So each
failure path performs exactly one `record`, on the same side of the same work,
and a future path that skips it would be a timing oracle as well as a missing
entry.

The exception is a second step whose challenge names a user id that no longer
exists, which has no subject to attribute — see `_require_second_step_user`. The
throttle record is the other departure, and in the other direction: it is
recorded once per address per window rather than per attempt, because the
refusal costs the caller nothing and a row per refused request would be a write
amplifier handed to whoever is being refused.
"""

from __future__ import annotations

from dataclasses import dataclass
from hmac import compare_digest

from app.application.audit_subject import subject_for, unknown_subject
from app.domain.entities.actor import Actor
from app.domain.entities.audit import AuditAction
from app.domain.entities.user import User
from app.domain.exceptions import (
    InvalidCredentialsError,
    InvalidTotpError,
    RateLimitedError,
    TotpRequiredError,
)
from app.domain.ports.repositories import InvitationRepositoryPort, UserRepositoryPort
from app.domain.ports.security_ports import (
    AuditPort,
    PasswordHasherPort,
    SecretBoxPort,
    TotpPort,
)
from app.domain.services.login_throttle import LoginThrottle
from app.domain.services.token_service import TokenService
from app.shared.clock import Clock


@dataclass(frozen=True, slots=True)
class PasswordResult:
    user_id: str
    """Held by the caller between the two login steps. Carries no privilege
    on its own: a session is only issued after the TOTP step succeeds."""


class AuthenticateLocal:
    def __init__(
        self,
        users: UserRepositoryPort,
        hasher: PasswordHasherPort,
        totp: TotpPort,
        *,
        invitations: InvitationRepositoryPort,
        tokens: TokenService,
        throttle: LoginThrottle,
        secret_box: SecretBoxPort,
        audit: AuditPort,
        clock: Clock,
    ) -> None:
        self._users = users
        self._hasher = hasher
        self._totp = totp
        self._invitations = invitations
        self._tokens = tokens
        self._throttle = throttle
        self._secret_box = secret_box
        self._audit = audit
        self._clock = clock

    async def _throttled(self, login: str, *, client_ip: str, step: str) -> None:
        """Record the throttle firing. The caller re-raises.

        This is the closest thing the platform has to the "alerting on repeated
        failures" section 5.3 promises: the limiter already knows when attempts
        have become abusive, and until now that knowledge lived in a Redis
        counter that expires. A row here is what an operator or a future alert
        rule can actually query.

        **Once per address per window**, claimed through the limiter that owns
        the window. Recording every refused request would hand an attacker who
        is already being refused a free unauthenticated write, which is the
        opposite of what a rate limiter is for; see `claim_refusal_record`.

        The account is resolved here rather than at the call site because this
        is the one path where the lookup is affordable: it happens once per
        window, after the request is already going to be refused. It matters
        because the audit read is tenant-scoped — attributed to `unknown` this
        row lands in the default tenant, and a tenant administrator watching an
        attack on their own user would see every `user.sign_in_failed` and none
        of the `user.sign_in_throttled` rows that say it became an attack.
        """
        if not await self._throttle.claim_refusal_record(client_ip=client_ip):
            return

        user = await self._users.get_by_login(login)
        subject = subject_for(user) if user else unknown_subject(login)

        await self._audit.record(
            subject,
            AuditAction.USER_SIGN_IN_THROTTLED,
            target=subject.id,
            outcome="denied",
            detail={"client_ip": client_ip, "step": step},
        )

    def _assert_still_usable(self, user: User) -> None:
        """Re-checked at the second step, not only the first.

        The challenge between password and TOTP lasts up to five minutes, and
        an account disabled inside that window would otherwise still complete
        the login and be issued a session. `resolve_session_actor` catches it
        on the next request, but "disable now" should take effect now. Same
        error as a missing second factor, so the step reveals nothing new.
        """
        if user.disabled_at is not None or not user.can_use_public_entrance:
            raise TotpRequiredError(detail=f"user {user.id} no longer usable")

    async def _require_second_step_user(self, user_id: str, *, client_ip: str) -> tuple[User, str]:
        """The account behind a challenge, still usable, with its TOTP secret.

        The secret is returned rather than re-read by the caller so that the
        "not null" it has just established survives into the type. Reading
        `user.totp_secret` again would be `str | None` there, and the caller
        would need either a second check or an `assert` that `python -O`
        strips — the same reasoning `verify_password` records about
        `password_hash`.

        Shared by both second-step methods so the three refusals below are
        audited in one place rather than twice — and they were audited in
        neither until the review of 2026-08-02 pointed out that the module
        docstring claimed every outcome was recorded while these raised
        silently. The disabled case is the one an incident review looks for:
        an administrator disables an account inside the five-minute challenge
        window, and "disable now takes effect now" should be visible.

        `user is None` is the one refusal with nothing to attribute — the id
        came from a challenge this server minted, so it means the account was
        deleted mid-window. A subject invented for it would be a fiction an
        investigation then has to rule out.
        """
        user = await self._users.get(user_id)
        if user is None:
            raise TotpRequiredError(detail=f"no user {user_id}")

        secret = user.totp_secret
        if secret is None:
            await self._fail(subject_for(user), client_ip=client_ip, reason="totp_not_enrolled")
            raise TotpRequiredError()

        try:
            self._assert_still_usable(user)
        except TotpRequiredError:
            await self._fail(subject_for(user), client_ip=client_ip, reason="account_unusable")
            raise

        return user, secret

    async def _fail(self, subject: Actor, *, client_ip: str, reason: str) -> None:
        """One record per rejected attempt, on every path.

        `reason` separates the cases the *response* deliberately does not, which
        is the point: the caller must not learn whether the login exists, and
        the operator reading the log after the fact must. The log is behind
        `logs:read`, so the two audiences never overlap.
        """
        await self._audit.record(
            subject,
            AuditAction.USER_SIGN_IN_FAILED,
            target=subject.id,
            outcome="failed",
            detail={"client_ip": client_ip, "reason": reason},
        )

    async def verify_password(self, login: str, password: str, *, client_ip: str) -> PasswordResult:
        # Before the hash, not after. See LoginThrottle.assert_allowed.
        try:
            await self._throttle.assert_allowed(login=login, client_ip=client_ip)
        except RateLimitedError:
            await self._throttled(login, client_ip=client_ip, step="password")
            raise

        user = await self._users.get_by_login(login)

        if user is None:
            # Burn comparable time before failing, so response latency does
            # not distinguish an unknown login from a wrong password. Without
            # this, timing enumerates valid accounts.
            await self._hasher.dummy_verify()
            await self._throttle.record_failure(login=login, client_ip=client_ip)
            await self._fail(unknown_subject(login), client_ip=client_ip, reason="unknown_login")
            raise InvalidCredentialsError(detail=f"unknown login={login}")

        if user.disabled_at is not None:
            await self._hasher.dummy_verify()
            await self._throttle.record_failure(login=login, client_ip=client_ip)
            await self._fail(subject_for(user), client_ip=client_ip, reason="account_disabled")
            raise InvalidCredentialsError(detail=f"disabled user={user.id}")

        if not user.can_use_public_entrance:
            # Tailnet-only account, or an invitation that was never completed.
            # Same error as above: whether an account has local credentials is
            # not something an unauthenticated caller should be able to probe.
            await self._hasher.dummy_verify()
            await self._throttle.record_failure(login=login, client_ip=client_ip)
            await self._fail(subject_for(user), client_ip=client_ip, reason="no_local_credentials")
            raise InvalidCredentialsError(detail=f"no local credentials user={user.id}")

        # Implied by can_use_public_entrance above, but bound to a local so the
        # narrowing survives without an `assert`, which python -O would strip.
        password_hash = user.password_hash
        if password_hash is None or not await self._hasher.verify(password, password_hash):
            await self._throttle.record_failure(login=login, client_ip=client_ip)
            await self._fail(subject_for(user), client_ip=client_ip, reason="bad_password")
            raise InvalidCredentialsError(detail=f"bad password user={user.id}")

        # Deliberately not cleared here. The counters are cleared only once the
        # second factor has also succeeded, so a valid password alone cannot be
        # used to reset the limiter and grind at the TOTP step indefinitely.
        #
        # Nothing is audited on this path either, and for the same reason: a
        # correct password is not a sign-in. The event section 12 asks for is
        # the one that produces a session, and that is the second step.
        return PasswordResult(user_id=user.id)

    async def verify_totp(self, user_id: str, code: str, *, client_ip: str) -> User:
        user, totp_secret = await self._require_second_step_user(user_id, client_ip=client_ip)
        subject = subject_for(user)

        try:
            await self._throttle.assert_allowed(login=user.login, client_ip=client_ip)
        except RateLimitedError:
            await self._throttled(user.login, client_ip=client_ip, step="totp")
            raise

        try:
            # Raises InvalidTotpError on a bad code or on one outside the window.
            counter = self._totp.verify(
                self._secret_box.decrypt(totp_secret), code, user.totp_last_counter
            )
        except InvalidTotpError:
            await self._throttle.record_failure(login=user.login, client_ip=client_ip)
            await self._fail(subject, client_ip=client_ip, reason="bad_totp_code")
            raise

        # The replay check is the UPDATE, not a comparison here. Two requests
        # carrying the same code would both read the same prior counter, both
        # pass a Python check, and both be admitted; only one can win a
        # conditional write. This is what makes a code observed in a phishing
        # proxy useless for a second login inside its window.
        if not await self._users.advance_totp_counter(user.id, counter):
            await self._throttle.record_failure(login=user.login, client_ip=client_ip)
            # Distinguished from a wrong code on purpose: this one means a
            # second request presented the same code at the same moment. A
            # *sequential* replay never reaches here — `totp.verify` rejects a
            # counter at or below the stored one and reports `bad_totp_code`,
            # which by then it is. Worth knowing when reading the log, because
            # the reasons do not partition the way their names suggest.
            await self._fail(subject, client_ip=client_ip, reason="totp_replay")
            raise InvalidTotpError(detail=f"replayed counter={counter} user={user.id}")

        await self._throttle.clear(login=user.login, client_ip=client_ip)
        await self._signed_in(subject, client_ip=client_ip, factor="totp")
        return user

    async def verify_recovery_code(self, user_id: str, presented: str, *, client_ip: str) -> User:
        """Second-step alternative when the authenticator is lost.

        A recovery code bypasses the second factor outright, so it is checked
        by digest comparison against the stored hashes and claimed with the
        same conditional UPDATE the TOTP counter uses. Nothing here reveals how
        many codes remain; that belongs to an authenticated view of the
        account, not to the login screen.
        """
        user, _ = await self._require_second_step_user(user_id, client_ip=client_ip)
        subject = subject_for(user)

        try:
            await self._throttle.assert_allowed(login=user.login, client_ip=client_ip)
        except RateLimitedError:
            await self._throttled(user.login, client_ip=client_ip, step="recovery_code")
            raise

        digest = self._tokens.hash_recovery_code(presented)
        stored = await self._invitations.list_recovery_codes(user.id)

        claimed = False
        for candidate in stored:
            if candidate.used_at is not None:
                continue
            if not compare_digest(candidate.code_hash, digest):
                continue
            claimed = await self._invitations.consume_recovery_code(candidate.id, self._clock.now())
            break

        if not claimed:
            await self._throttle.record_failure(login=user.login, client_ip=client_ip)
            await self._fail(subject, client_ip=client_ip, reason="no_recovery_code_matched")
            raise InvalidTotpError(detail=f"no unused recovery code matched user={user.id}")

        await self._throttle.clear(login=user.login, client_ip=client_ip)

        # Two rows, not one, and the second is not redundant. `user.signed_in`
        # says a session was granted; this says a single-use credential was
        # spent, which is a fact about the account's recovery state rather than
        # about this login. Counting them answers "how many codes are gone"
        # without reading inside anyone's `detail`, and section 12 names
        # recovery code use as its own event for the same reason: bypassing the
        # second factor is worth seeing without knowing to look for it.
        await self._audit.record(subject, AuditAction.USER_RECOVERY_CODE_USED, target=user.id)
        await self._signed_in(subject, client_ip=client_ip, factor="recovery_code")
        return user

    async def _signed_in(self, subject: Actor, *, client_ip: str, factor: str) -> None:
        await self._audit.record(
            subject,
            AuditAction.USER_SIGNED_IN,
            target=subject.id,
            detail={"client_ip": client_ip, "factor": factor},
        )
