"""Sign in, refresh token rotation, sign out and password change (`security.md` section 1).

Functions that must keep a record even when they refuse (a failed login, a reused refresh
token) finish their transaction first and return an outcome. The endpoint turns the outcome
into the response, so the refusal is never rolled back with the work it refused.
"""

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import AuditAction, AuditService, RequestMeta, email_fingerprint
from app.core.clock import now_utc
from app.core.config import Settings
from app.core.db import transaction
from app.core.errors import AppError
from app.core.messages import (
    CURRENT_PASSWORD_WRONG,
    EMAIL_TAKEN,
    LOGIN_FAILED,
    NEW_PASSWORD_SAME,
    ErrorCode,
)
from app.core.ratelimit import keyed_limits, unknown_email_failures
from app.core.security import (
    PasswordPolicyError,
    PasswordService,
    hash_refresh_token,
    issue_access_token,
    new_refresh_token,
    validate_password,
)
from app.models.tenancy import BusinessSettings, RefreshToken, Tenant, User
from app.schemas.common import ErrorDetail

MAX_FAILURES = 5
LOCKOUT_MINUTES = 15
FAILURE_WINDOW = timedelta(minutes=LOCKOUT_MINUTES)
SLUG_UNSAFE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class IssuedSession:
    """What a successful sign in or refresh hands back to the endpoint."""

    access_token: str
    expires_in: int
    refresh_token: str
    user: User
    tenant: Tenant


class RefreshOutcome(StrEnum):
    ROTATED = "rotated"
    UNKNOWN = "unknown"
    EXPIRED = "expired"
    REUSED = "reused"
    GRACE = "grace"
    INACTIVE = "inactive"


@dataclass(frozen=True)
class RefreshResult:
    outcome: RefreshOutcome
    issued: IssuedSession | None = None

    @property
    def clear_cookie(self) -> bool:
        """After a grace window refusal the browser may already hold the newer cookie."""
        return self.outcome not in {RefreshOutcome.ROTATED, RefreshOutcome.GRACE}


class AuthService:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        passwords: PasswordService,
        meta: RequestMeta,
    ) -> None:
        self.session = session
        self.settings = settings
        self.passwords = passwords
        self.meta = meta
        self.audit = AuditService(session)

    # ------------------------------------------------------------------ sign in

    def login(self, email: str, password: str) -> IssuedSession:
        """Verify credentials and open a session, or raise the generic failure.

        Exactly one password verification runs on every path, so timing does not reveal
        whether the email has an account.
        """
        email = email.strip().lower()
        retry_after = keyed_limits.hit("login-email", self.settings.rate_limit_login_email, email)
        if retry_after is not None:
            raise AppError(ErrorCode.RATE_LIMITED, headers={"Retry-After": str(retry_after)})

        now = now_utc()
        failure: AppError | None
        with transaction(self.session):
            row = self.session.execute(
                select(User, Tenant)
                .join(Tenant, Tenant.id == User.tenant_id)
                .where(User.email == email)
                .with_for_update(of=User)
            ).first()

            if row is None:
                locked_for = self._unknown_email_failure(email, password)
                failure = _login_failure(locked_for)
                self.audit.record(
                    AuditAction.LOGIN_FAILURE,
                    tenant_id=None,
                    user_id=None,
                    meta=self.meta,
                    after={"email_hash": email_fingerprint(email), "reason": "unknown"},
                )
            else:
                user, tenant = row
                failure = self._check_known_user(user, tenant, password, email, now)
                if failure is None:
                    return self._open_session(user, tenant, now, AuditAction.LOGIN_SUCCESS)
        # Reached only on failure: the failure bookkeeping above is committed, now refuse.
        raise failure or AppError(ErrorCode.INTERNAL)

    def _unknown_email_failure(self, email: str, password: str) -> int | None:
        """Mirror the lockout of real accounts so a locked answer proves nothing."""
        self.passwords.verify_unknown(password)
        if unknown_email_failures.count(email) >= MAX_FAILURES:
            return LOCKOUT_MINUTES * 60
        if unknown_email_failures.add(email) >= MAX_FAILURES:
            return LOCKOUT_MINUTES * 60
        return None

    def _check_known_user(
        self, user: User, tenant: Tenant, password: str, email: str, now: datetime
    ) -> AppError | None:
        """Bookkeeping for an existing account. Returns the failure to raise, or None."""
        if user.locked_until is not None and user.locked_until > now:
            self.passwords.verify_unknown(password)
            remaining = int((user.locked_until - now).total_seconds()) + 1
            return _login_failure(remaining)

        valid = self.passwords.verify(user.password_hash, password)
        if valid and user.is_active and tenant.is_active:
            if self.passwords.needs_rehash(user.password_hash):
                user.password_hash = self.passwords.hash(password)
            user.failed_login_count = 0
            user.locked_until = None
            user.last_failed_login_at = None
            user.last_login_at = now
            unknown_email_failures.clear(email)
            return None

        reason = "inactive" if valid else "password"
        locked_for = self._register_failure(user, now)
        self.audit.record(
            AuditAction.LOGIN_FAILURE,
            tenant_id=user.tenant_id,
            user_id=user.id,
            meta=self.meta,
            after={"email_hash": email_fingerprint(email), "reason": reason},
        )
        return _login_failure(locked_for)

    def _register_failure(self, user: User, now: datetime) -> int | None:
        """Count a failed attempt. Returns the lock length in seconds when it locks."""
        recent = (
            user.last_failed_login_at is not None
            and now - user.last_failed_login_at < FAILURE_WINDOW
        )
        user.failed_login_count = user.failed_login_count + 1 if recent else 1
        user.last_failed_login_at = now
        if user.failed_login_count < MAX_FAILURES:
            return None
        user.locked_until = now + FAILURE_WINDOW
        self.audit.record(
            AuditAction.LOCKOUT,
            tenant_id=user.tenant_id,
            user_id=user.id,
            meta=self.meta,
            after={"locked_until": user.locked_until, "failures": user.failed_login_count},
        )
        return LOCKOUT_MINUTES * 60

    # ------------------------------------------------------------------ sessions

    def _open_session(
        self,
        user: User,
        tenant: Tenant,
        now: datetime,
        action: AuditAction,
        *,
        audit_detail: dict[str, str] | None = None,
    ) -> IssuedSession:
        issued, _ = self._issue(user, tenant, family_id=uuid.uuid4(), now=now)
        self.audit.record(
            action,
            tenant_id=user.tenant_id,
            user_id=user.id,
            meta=self.meta,
            after=audit_detail,
        )
        return issued

    def _issue(
        self, user: User, tenant: Tenant, *, family_id: uuid.UUID, now: datetime
    ) -> tuple[IssuedSession, RefreshToken]:
        raw, token_hash = new_refresh_token()
        row = RefreshToken(
            tenant_id=user.tenant_id,
            user_id=user.id,
            family_id=family_id,
            token_hash=token_hash,
            issued_at=now,
            expires_at=now + timedelta(days=self.settings.refresh_token_days),
            user_agent=self.meta.user_agent,
            ip=self.meta.ip,
        )
        self.session.add(row)
        self.session.flush()
        access, expires_in = issue_access_token(
            self.settings, user_id=user.id, tenant_id=user.tenant_id, role=user.role, now=now
        )
        issued = IssuedSession(
            access_token=access,
            expires_in=expires_in,
            refresh_token=raw,
            user=user,
            tenant=tenant,
        )
        return issued, row

    # ------------------------------------------------------------------ refresh

    def refresh(self, raw_token: str | None) -> RefreshResult:
        """Rotate a refresh token. Reuse of a spent token revokes the whole family."""
        if not raw_token:
            return RefreshResult(RefreshOutcome.UNKNOWN)
        now = now_utc()
        token_hash = hash_refresh_token(raw_token)
        with transaction(self.session):
            current = self.session.execute(
                select(RefreshToken).where(RefreshToken.token_hash == token_hash).with_for_update()
            ).scalar_one_or_none()
            if current is None:
                return RefreshResult(RefreshOutcome.UNKNOWN)

            spent = current.rotated_at is not None or current.revoked_at is not None
            if spent:
                if self._within_grace(current, now):
                    return RefreshResult(RefreshOutcome.GRACE)
                self._revoke_family(current.family_id, "reuse_detected", now)
                self.audit.record(
                    AuditAction.REFRESH_REUSE,
                    tenant_id=current.tenant_id,
                    user_id=current.user_id,
                    meta=self.meta,
                    entity_type="refresh_token_family",
                    entity_id=current.family_id,
                )
                return RefreshResult(RefreshOutcome.REUSED)

            if current.expires_at <= now:
                current.revoked_at = now
                current.revoked_reason = "expired"
                return RefreshResult(RefreshOutcome.EXPIRED)

            row = self.session.execute(
                select(User, Tenant)
                .join(Tenant, Tenant.id == User.tenant_id)
                .where(User.id == current.user_id)
            ).first()
            if row is None or not row[0].is_active or not row[1].is_active:
                self._revoke_family(current.family_id, "logout_all", now)
                return RefreshResult(RefreshOutcome.INACTIVE)
            user, tenant = row

            issued, successor = self._issue(user, tenant, family_id=current.family_id, now=now)
            current.rotated_at = now
            current.last_used_at = now
            current.replaced_by_id = successor.id
            return RefreshResult(RefreshOutcome.ROTATED, issued)

    def _within_grace(self, spent: RefreshToken, now: datetime) -> bool:
        """Two tabs refreshing together: the loser presents a token rotated moments ago whose
        successor nobody has used yet. That is a race, not theft."""
        if spent.rotated_at is None or spent.revoked_at is not None or spent.replaced_by_id is None:
            return False
        if now - spent.rotated_at >= timedelta(seconds=self.settings.refresh_grace_seconds):
            return False
        successor = self.session.execute(
            select(RefreshToken).where(
                RefreshToken.tenant_id == spent.tenant_id, RefreshToken.id == spent.replaced_by_id
            )
        ).scalar_one_or_none()
        return (
            successor is not None
            and successor.rotated_at is None
            and successor.revoked_at is None
            and successor.last_used_at is None
        )

    def _revoke_family(self, family_id: uuid.UUID, reason: str, now: datetime) -> None:
        self.session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now, revoked_reason=reason)
        )

    # ------------------------------------------------------------------ sign out

    def logout(self, raw_token: str | None) -> None:
        """Revoke the session that holds this refresh token. Unknown tokens are ignored."""
        if not raw_token:
            return
        now = now_utc()
        with transaction(self.session):
            current = self.session.execute(
                select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw_token))
            ).scalar_one_or_none()
            if current is None:
                return
            self._revoke_family(current.family_id, "logout", now)
            self.audit.record(
                AuditAction.LOGOUT,
                tenant_id=current.tenant_id,
                user_id=current.user_id,
                meta=self.meta,
            )

    def logout_all(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> None:
        now = now_utc()
        with transaction(self.session):
            self._revoke_user_tokens(tenant_id, user_id, "logout_all", now)
            self.audit.record(
                AuditAction.LOGOUT_ALL, tenant_id=tenant_id, user_id=user_id, meta=self.meta
            )

    def _revoke_user_tokens(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        reason: str,
        now: datetime,
        *,
        keep_family: uuid.UUID | None = None,
    ) -> None:
        stmt = update(RefreshToken).where(
            RefreshToken.tenant_id == tenant_id,
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_(None),
        )
        if keep_family is not None:
            stmt = stmt.where(RefreshToken.family_id != keep_family)
        self.session.execute(stmt.values(revoked_at=now, revoked_reason=reason))

    # ------------------------------------------------------------------ password

    def change_password(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        current_password: str,
        new_password: str,
        *,
        current_refresh_token: str | None,
    ) -> None:
        """Change the password and end every other session. The session making the change,
        found through its refresh cookie, stays signed in."""
        now = now_utc()
        failed_for: int | None = None
        error: AppError | None = None
        with transaction(self.session):
            row = self.session.execute(
                select(User, Tenant)
                .join(Tenant, Tenant.id == User.tenant_id)
                .where(User.id == user_id, User.tenant_id == tenant_id)
                .with_for_update(of=User)
            ).first()
            if row is None:
                raise AppError(ErrorCode.UNAUTHENTICATED)
            user, tenant = row

            if user.locked_until is not None and user.locked_until > now:
                self.passwords.verify_unknown(current_password)
                retry = str(int((user.locked_until - now).total_seconds()) + 1)
                raise AppError(ErrorCode.RATE_LIMITED, headers={"Retry-After": retry})

            if not self.passwords.verify(user.password_hash, current_password):
                failed_for = self._register_failure(user, now)
                self.audit.record(
                    AuditAction.LOGIN_FAILURE,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    meta=self.meta,
                    after={"reason": "change_password"},
                )
                error = AppError(
                    ErrorCode.VALIDATION_ERROR,
                    CURRENT_PASSWORD_WRONG,
                    details=[ErrorDetail(field="current_password", issue="is not right")],
                )
            else:
                error = self._apply_new_password(
                    user, tenant, current_password, new_password, current_refresh_token, now
                )
                if error is not None:
                    # A rejected new password must not undo the successful verification above.
                    user.failed_login_count = 0
        if error is not None:
            if failed_for is not None:
                error.headers["Retry-After"] = str(failed_for)
            raise error

    def _apply_new_password(
        self,
        user: User,
        tenant: Tenant,
        current_password: str,
        new_password: str,
        current_refresh_token: str | None,
        now: datetime,
    ) -> AppError | None:
        if new_password == current_password:
            return AppError(
                ErrorCode.VALIDATION_ERROR,
                NEW_PASSWORD_SAME,
                details=[ErrorDetail(field="new_password", issue="must be different")],
            )
        try:
            validate_password(new_password, email=user.email, business_name=tenant.name)
        except PasswordPolicyError as exc:
            return AppError(
                ErrorCode.VALIDATION_ERROR,
                str(exc),
                details=[ErrorDetail(field="new_password", issue="does not meet the rules")],
            )
        user.password_hash = self.passwords.hash(new_password)
        user.password_changed_at = now
        user.failed_login_count = 0
        user.locked_until = None
        user.last_failed_login_at = None

        keep: uuid.UUID | None = None
        if current_refresh_token:
            keep = self.session.execute(
                select(RefreshToken.family_id).where(
                    RefreshToken.tenant_id == user.tenant_id,
                    RefreshToken.user_id == user.id,
                    RefreshToken.token_hash == hash_refresh_token(current_refresh_token),
                    RefreshToken.revoked_at.is_(None),
                )
            ).scalar_one_or_none()
        self._revoke_user_tokens(user.tenant_id, user.id, "password_change", now, keep_family=keep)
        self.audit.record(
            AuditAction.PASSWORD_CHANGE,
            tenant_id=user.tenant_id,
            user_id=user.id,
            meta=self.meta,
        )
        return None

    # ------------------------------------------------------------------ flagged flows

    def register(
        self,
        *,
        business_name: str,
        business_type: str,
        full_name: str,
        email: str,
        password: str,
    ) -> IssuedSession:
        """Create a tenant and its owner. Only reachable when `ALLOW_REGISTRATION` is on."""
        try:
            validate_password(password, email=email, business_name=business_name)
        except PasswordPolicyError as exc:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                str(exc),
                details=[ErrorDetail(field="password", issue="does not meet the rules")],
            ) from exc
        now = now_utc()
        password_hash = self.passwords.hash(password)
        try:
            with transaction(self.session):
                taken = self.session.execute(select(User.id).where(User.email == email)).first()
                if taken is not None:
                    raise AppError(ErrorCode.CONFLICT, EMAIL_TAKEN)
                tenant = Tenant(
                    slug=self._free_slug(business_name),
                    name=business_name,
                    business_type=business_type,
                    is_synthetic=False,
                )
                self.session.add(tenant)
                self.session.flush()
                user = User(
                    tenant_id=tenant.id,
                    email=email,
                    password_hash=password_hash,
                    full_name=full_name,
                    role="owner",
                    last_login_at=now,
                )
                self.session.add(user)
                self.session.add(BusinessSettings(tenant_id=tenant.id))
                self.session.flush()
                issued = self._open_session(user, tenant, now, AuditAction.REGISTER)
        except IntegrityError as exc:
            # Two sign ups with the same email racing past the check above.
            raise AppError(ErrorCode.CONFLICT, EMAIL_TAKEN) from exc
        return issued

    def _free_slug(self, business_name: str) -> str:
        base = SLUG_UNSAFE.sub("-", business_name.lower()).strip("-")[:40] or "business"
        slug = base
        while self.session.execute(select(Tenant.id).where(Tenant.slug == slug)).first():
            slug = f"{base}-{uuid.uuid4().hex[:6]}"
        return slug

    def demo_login(self, profile_key: str) -> IssuedSession:
        """Open a session for a synthetic tenant without a password. The flag is checked by
        the endpoint, the synthetic check is here so no caller can skip it."""
        now = now_utc()
        with transaction(self.session):
            row = self.session.execute(
                select(User, Tenant)
                .join(Tenant, Tenant.id == User.tenant_id)
                .where(
                    Tenant.profile_key == profile_key,
                    Tenant.is_synthetic.is_(True),
                    Tenant.is_active.is_(True),
                    User.is_active.is_(True),
                    User.role == "owner",
                )
                .order_by(User.created_at)
                .limit(1)
            ).first()
            if row is None:
                raise AppError(ErrorCode.NOT_FOUND)
            user, tenant = row
            user.last_login_at = now
            return self._open_session(
                user, tenant, now, AuditAction.LOGIN_SUCCESS, audit_detail={"via": "demo"}
            )


def _login_failure(locked_for_seconds: int | None) -> AppError:
    headers = {"Retry-After": str(locked_for_seconds)} if locked_for_seconds else {}
    return AppError(ErrorCode.UNAUTHENTICATED, LOGIN_FAILED, headers=headers)
