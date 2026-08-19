"""Shared authentication throttle, audit, and session completion."""

from __future__ import annotations

from app.application.audit_subject import subject_for, unknown_subject
from app.domain.entities.actor import Actor
from app.domain.entities.audit import AuditAction
from app.domain.entities.user import User
from app.domain.exceptions import (
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


class AuthenticationCoordination:
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

    async def _signed_in(self, subject: Actor, *, client_ip: str, factor: str) -> None:
        await self._audit.record(
            subject,
            AuditAction.USER_SIGNED_IN,
            target=subject.id,
            detail={"client_ip": client_ip, "factor": factor},
        )
