"""Run release checks in a disposable, socket-only PostgreSQL cluster.

Usage: .venv/bin/python scripts/verify_local_postgres.py
Requires initdb, pg_ctl and createdb on PATH. Never uses DATABASE_URL or .env.
"""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile


def main():
    binaries = {name: shutil.which(name) for name in ("initdb", "pg_ctl", "createdb")}
    if not all(binaries.values()):
        raise SystemExit("Install PostgreSQL server tools and add them to PATH first.")
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="valid-pg-", dir="/tmp") as directory:
        cluster = str(Path(directory) / "data")
        log = str(Path(directory) / "postgres.log")
        env = {"PATH": os.environ["PATH"], "HOME": directory, "LC_ALL": "C"}
        subprocess.run([binaries["initdb"], "-D", cluster, "-U", "valid_test",
                        "--auth-local=trust", "--auth-host=reject", "--no-locale", "-E", "UTF8"],
                       env=env, check=True, stdout=subprocess.DEVNULL)
        try:
            subprocess.run([binaries["pg_ctl"], "-D", cluster, "-l", log, "-w", "start",
                            "-o", f"-k {directory} -h '' -p 55432 -c timezone=America/Chicago"], env=env, check=True)
            subprocess.run([binaries["createdb"], "-h", directory, "-p", "55432", "-U", "valid_test",
                            "valid_release_test"], env=env, check=True)
            env.update({
                "PYTHONPATH": str(root / "server"),
                "VALID_LOCAL_POSTGRES_TEST": "1",
                "DATABASE_URL": f"postgresql+asyncpg://valid_test@/valid_release_test?host={directory}&port=55432",
                "UPLOAD_TOKEN_SECRET": "local-postgres-upload-secret",
                "DASHBOARD_AUTH_SECRET": "local-postgres-dashboard-secret",
                "SESSION_HMAC_SECRET": "local-postgres-session-secret",
                "AGGREGATE_DP_NOISE_SECRET": "local-postgres-noise-secret",
                "BILLING_ENABLED": "false",
                "AUTO_CREATE_DB_SCHEMA": "false",
                "ENABLE_PROD_SCHEDULER": "false",
                "STRIPE_SECRET_KEY": "sk_test_local_only",
                "STRIPE_WEBHOOK_SECRET": "whsec_local_only",
                "STRIPE_SOLO_PRICE_ID": "price_local_solo",
                "STRIPE_STANDARD_PRICE_ID": "price_local_standard",
                "STRIPE_ADDITIONAL_SITE_PRICE_ID": "price_local_extra",
                "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            })
            result = subprocess.run([sys.executable, "-m", "pytest", "-v", "-p", "no:cacheprovider",
                                     str(root / "server" / "postgres_tests")], cwd=directory, env=env, timeout=180)
        finally:
            if Path(cluster, "postmaster.pid").exists():
                subprocess.run([binaries["pg_ctl"], "-D", cluster, "-m", "fast", "-w", "stop"],
                               env=env, check=True)
            if Path(log).exists():
                print("PostgreSQL log (last 12 lines):", flush=True)
                print("\n".join(Path(log).read_text().splitlines()[-12:]), flush=True)
        return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
