"""``speaker-roi admin ...`` - the operator commands that need the API's own security code.

Separate from the core CLI, and mounted into it conditionally, for the same reason the synthetic
generator is: this module imports the password hasher and the session model, and the core package
must not depend on the API package. Mounting inverts that - the core CLI asks whether this is
importable and adds the sub-command if it is, so a core-only image simply has no ``admin`` group
rather than a broken one.

Every command here is a thin argument parser over :mod:`speaker_roi_api.services.bootstrap`. The
decisions live there; what lives here is how a password is obtained without ever putting it on a
command line, and how a failure is turned into a message and an exit code rather than a traceback.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Annotated

import typer

from speaker_roi_core.enums import Role

if TYPE_CHECKING:
    from speaker_roi_api.services.bootstrap import BootstrapResult

admin_app = typer.Typer(
    name="admin",
    help="First-run provisioning and account operations.",
    no_args_is_help=True,
    # Locals here hold a plaintext password and a DSN.
    pretty_exceptions_show_locals=False,
)

#: Where a non-interactive run is expected to put the password.
#:
#: An environment variable rather than a flag: a variable can be injected by a secret manager
#: without appearing in the process table, and the shell will not record it in history the way it
#: records an argument. It is read once and never echoed.
PASSWORD_ENV = "SPEAKER_ROI_ADMIN_PASSWORD"  # noqa: S105 - a variable name, not a credential


def _resolve_password(*, allow_generate: bool, prompt_label: str) -> str | None:
    """Take the password from the environment, or a prompt, or return ``None`` to generate one.

    Returning ``None`` rather than generating here keeps the generation in the service, where the
    policy check that validates it also lives. The precedence - environment before prompt - is what
    makes the same command usable from a container hook and from a terminal without a flag to
    switch between them.
    """
    from_env = os.environ.get(PASSWORD_ENV)
    if from_env:
        return from_env
    # `isatty` and not a `--no-input` flag: the question being asked is genuinely "is there a human
    # here to answer", and a start-up hook with no terminal should not block forever on a prompt
    # that nothing will ever type into.
    import sys

    if sys.stdin.isatty():
        typed = typer.prompt(prompt_label, hide_input=True, confirmation_prompt=True, default="")
        if typed:
            return str(typed)
    if allow_generate:
        return None
    raise typer.BadParameter(
        f"no password available: set {PASSWORD_ENV} or run this from a terminal",
        param_hint=PASSWORD_ENV,
    )


def _report(result: BootstrapResult) -> None:
    """Print what happened, then the next steps, then the password if one was generated.

    The password goes last on purpose. It is the thing the operator must copy, and a value printed
    above ten lines of status is a value that scrolls out of a small terminal.
    """
    mark = {True: "created", False: "already existed"}
    typer.echo("")
    typer.echo(f"  tenant      {result.tenant_code}  ({mark[result.tenant_created]})")
    typer.echo(f"              id {result.tenant_id}")
    typer.echo(f"  user        {result.user_email}  ({mark[result.user_created]})")
    typer.echo(f"              id {result.user_id}")
    typer.echo(f"  membership  {result.membership_role}  ({mark[result.membership_created]})")
    typer.echo(
        f"  taxonomy    {result.taxonomy.created} created, "
        f"{result.taxonomy.existing} already present"
    )
    typer.echo("")
    if not result.changed_anything:
        typer.echo("Nothing to do - this tenant was already provisioned.")
    if result.mfa_enrolment_required:
        typer.echo(
            "This role requires a second factor. The first login returns "
            "mfaEnrolmentRequired=true; call POST /api/v1/auth/mfa/enrol and then "
            "/auth/mfa/enrol/confirm with a code from the authenticator to finish."
        )
    if result.generated_password is not None:
        typer.echo("")
        typer.secho("  Generated password (shown once, change on first login):", bold=True)
        typer.secho(f"  {result.generated_password}", fg=typer.colors.YELLOW, bold=True)
        typer.echo("")


@admin_app.command("bootstrap")
def bootstrap_command(
    tenant_code: Annotated[
        str, typer.Option("--tenant-code", help="Short immutable key, e.g. 'acme-pharma'.")
    ],
    tenant_name: Annotated[str, typer.Option("--tenant-name", help="Display name.")],
    email: Annotated[str, typer.Option("--email", help="Administrator's email address.")],
    display_name: Annotated[str, typer.Option("--name", help="Administrator's display name.")],
    role: Annotated[
        Role, typer.Option("--role", help="Tenant role for the administrator.")
    ] = Role.PHARMA_ADMIN,
    platform_admin: Annotated[
        bool,
        typer.Option(
            "--platform-admin/--no-platform-admin",
            help="Also mark the account a platform administrator. This grants tenant "
            "*administration* rights, not the right to read tenant business data.",
        ),
    ] = False,
    country: Annotated[str, typer.Option("--country", help="ISO-3166 alpha-2.")] = "IN",
    currency: Annotated[str, typer.Option("--currency", help="Reporting currency.")] = "INR",
    locale: Annotated[str, typer.Option("--locale")] = "en-IN",
    timezone: Annotated[str, typer.Option("--timezone")] = "Asia/Kolkata",
    fiscal_year_start_month: Annotated[int, typer.Option("--fiscal-year-start", min=1, max=12)] = 4,
    synthetic_mode: Annotated[
        bool,
        typer.Option(
            "--synthetic/--real",
            help="Mark the tenant's data as synthetic. Set this for the demo tenant: it is what "
            "stops a generated figure being exported as though it were measured.",
        ),
    ] = False,
    with_taxonomy: Annotated[
        bool, typer.Option("--with-taxonomy/--no-taxonomy", help="Seed the default vocabularies.")
    ] = True,
) -> None:
    """Create a tenant, its first administrator, their membership and the default taxonomy.

    Safe to re-run: existing rows are reported and left alone. Notably it will not reset the
    password of an administrator who already exists - use ``admin reset-password`` for that, which
    also revokes their sessions.
    """
    from speaker_roi_api.services import bootstrap as svc
    from speaker_roi_core.cli import _run

    password = _resolve_password(
        allow_generate=True, prompt_label="Password for the new administrator"
    )
    result = _run(
        svc.bootstrap(
            tenant_code=tenant_code,
            tenant_name=tenant_name,
            email=email,
            display_name=display_name,
            password=password,
            role=role,
            platform_admin=platform_admin,
            country=country,
            currency=currency,
            locale=locale,
            timezone=timezone,
            fiscal_year_start_month=fiscal_year_start_month,
            synthetic_mode=synthetic_mode,
            with_taxonomy=with_taxonomy,
        )
    )
    _report(result)


@admin_app.command("reset-password")
def reset_password_command(
    email: Annotated[str, typer.Option("--email", help="Account to reset.")],
) -> None:
    """Set a new local password, clear any lockout, and revoke every session the account holds."""
    from speaker_roi_api.services import bootstrap as svc
    from speaker_roi_core.cli import _run

    password = _resolve_password(allow_generate=True, prompt_label="New password")
    _, generated = _run(svc.reset_password(email=email, password=password))
    typer.echo("")
    typer.echo(f"  Password reset for {email}. Every active session was revoked.")
    if generated is not None:
        typer.secho("  Generated password (shown once):", bold=True)
        typer.secho(f"  {generated}", fg=typer.colors.YELLOW, bold=True)
    typer.echo("")


@admin_app.command("grant-role")
def grant_role_command(
    email: Annotated[str, typer.Option("--email")],
    tenant_code: Annotated[str, typer.Option("--tenant-code")],
    role: Annotated[Role, typer.Option("--role")],
) -> None:
    """Add one role for one user in one tenant.

    Additive only. Revoking a role requires a reason on the record, so it belongs in the audited
    API path rather than in a command whose entire interface is three strings.
    """
    from speaker_roi_api.services import bootstrap as svc
    from speaker_roi_core.cli import _run

    changed = _run(svc.grant_role(email=email, tenant_code=tenant_code, role=role))
    verb = "granted" if changed else "already held"
    typer.echo(f"  {email} {verb} {role} in {tenant_code}.")


@admin_app.command("seed-taxonomy")
def seed_taxonomy_command(
    tenant_code: Annotated[str, typer.Option("--tenant-code")],
) -> None:
    """Add any missing default vocabulary rows to an existing tenant.

    Fills gaps only. A value an operator retired on purpose stays retired, and one they added
    stays untouched.
    """
    from sqlalchemy import func, select

    from speaker_roi_api.services import bootstrap as svc
    from speaker_roi_core.cli import _run
    from speaker_roi_core.db.session import platform_session_scope, session_scope
    from speaker_roi_core.errors import NotFoundError
    from speaker_roi_core.models.core import Tenant

    async def _body() -> svc.TaxonomyOutcome:
        async with platform_session_scope(reason="admin cli: resolve tenant") as db:
            tenant_id = (
                await db.execute(
                    select(Tenant.id).where(func.lower(Tenant.code) == tenant_code.lower())
                )
            ).scalar_one_or_none()
            if tenant_id is None:
                raise NotFoundError("tenant", tenant_code)
        async with session_scope(tenant_id=tenant_id) as db:
            return await svc.seed_taxonomy(db, tenant_id=tenant_id)

    outcome = _run(_body())
    typer.echo(f"  {outcome.created} created, {outcome.existing} already present.")


@admin_app.command("list-tenants")
def list_tenants_command() -> None:
    """Every tenant, for an operator orienting themselves in an unfamiliar environment."""
    from speaker_roi_api.services import bootstrap as svc
    from speaker_roi_core.cli import _run

    rows = _run(svc.list_tenants())
    if not rows:
        typer.echo("  No tenants. Run `speaker-roi admin bootstrap` to create one.")
        return
    typer.echo("")
    typer.echo(f"  {'CODE':<24} {'STATUS':<20} {'DATA':<10} NAME")
    for row in rows:
        kind = "synthetic" if row["synthetic_mode"] else "real"
        typer.echo(f"  {row['code']:<24} {row['status']:<20} {kind:<10} {row['name']}")
    typer.echo("")


__all__ = ["admin_app"]
