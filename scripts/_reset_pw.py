"""One-shot: reset admin password. Delete this file after use."""
import asyncio
from argon2 import PasswordHasher
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

async def reset():
    hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1, hash_len=32, salt_len=16)
    pw_hash = hasher.hash("admin@123")
    engine = create_async_engine(
        "postgresql+asyncpg://app_rw:app_rw_pw@127.0.0.1:54329/speaker_roi",
        poolclass=NullPool,
    )
    async with engine.begin() as conn:
        row = await conn.execute(text(
            "SELECT id, email, status, password_hash IS NOT NULL as has_pw, "
            "failed_login_count, locked_until "
            "FROM auth.users WHERE email = 'admin@demo.com'"
        ))
        user = row.first()
        if user is None:
            print("ERROR: No user with email admin@demo.com")
            return
        print(f"User: {user.id}, status={user.status}, has_password={user.has_pw}, "
              f"failed_logins={user.failed_login_count}, locked_until={user.locked_until}")

        await conn.execute(text(
            "UPDATE auth.users SET password_hash = :hash, "
            "failed_login_count = 0, locked_until = NULL "
            "WHERE email = 'admin@demo.com'"
        ), {"hash": pw_hash})
        print("Password reset to: admin@123")

        row2 = await conn.execute(text(
            "SELECT m.role, m.status, t.code "
            "FROM auth.memberships m JOIN core.tenants t ON t.id = m.tenant_id "
            "WHERE m.user_id = :uid"
        ), {"uid": user.id})
        for r in row2:
            print(f"Membership: role={r.role}, status={r.status}, tenant={r.code}")
    await engine.dispose()

asyncio.run(reset())
