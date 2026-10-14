"""Owner account commands that have no endpoint: `reset-password` (`D-030`)."""

import getpass
import os
import sys
import uuid

from sqlalchemy import select, update

from app.core.audit import AuditAction, AuditService, RequestMeta
from app.core.clock import now_utc
from app.core.config import get_settings
from app.core.db import get_session_factory, transaction
from app.core.security import PasswordPolicyError, PasswordService, validate_password
from app.models.tenancy import RefreshToken, Tenant, User

PASSWORD_ENV = "NEW_OWNER_PASSWORD"  # noqa: S105  name of a variable, not a secret


def out(line: str) -> None:
    sys.stdout.write(line + "\n")


def reset_password(email: str) -> int:
    """Set a new password for an owner, sign them out everywhere and unlock the account.

    The password comes from the `NEW_OWNER_PASSWORD` environment variable, or is asked for
    without echo. It is checked against the password policy and never printed or logged.
    """
    password = os.environ.get(PASSWORD_ENV) or getpass.getpass("New password: ")
    factory = get_session_factory()
    with factory() as session, transaction(session):
        user = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if user is None:
            out("No account has that email address.")
            return 2
        tenant = session.get(Tenant, user.tenant_id)
        try:
            validate_password(password, email=email, business_name=tenant.name if tenant else None)
        except PasswordPolicyError as exc:
            out(f"The password was not accepted: {exc}")
            return 2
        user.password_hash = PasswordService(get_settings()).hash(password)
        user.password_changed_at = now_utc()
        user.failed_login_count = 0
        user.locked_until = None
        session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now_utc(), revoked_reason="password_change")
        )
        AuditService(session).record(
            AuditAction.PASSWORD_RESET,
            tenant_id=user.tenant_id,
            user_id=user.id,
            meta=RequestMeta(ip=None, user_agent="cli", request_id=str(uuid.uuid4())),
            entity_type="user",
            entity_id=user.id,
        )
    out("Password updated. Every session for this account was signed out.")
    return 0
