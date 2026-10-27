"""Standalone migration smoke check against an isolated temporary PostgreSQL cluster.

Does not read DATABASE_URL or connect to an existing server. Requires local PostgreSQL binaries.
Run from the repository root: python backend/tests/check_postgres_migration.py --postgres-bin <bin-folder>
"""
import argparse
import os
from pathlib import Path
import socket
import subprocess
import tempfile



def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--postgres-bin", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = root / "output"
    output.mkdir(exist_ok=True)
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("PG")}
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    suffix = ".exe" if os.name == "nt" else ""

    def run(binary, *arguments):
        if binary == "pg_ctl" and "start" in arguments:
            # Windows postgres children may inherit pipe handles; a file avoids waiting for their EOF.
            control_log = Path(arguments[arguments.index("-D") + 1]).parent / "control.log"
            with control_log.open("w", encoding="utf-8") as log:
                result = subprocess.run([str(args.postgres_bin / (binary + suffix)), *map(str, arguments)],
                                        env=env, stdout=log, stderr=subprocess.STDOUT, creationflags=flags, timeout=45)
            if result.returncode:
                raise RuntimeError(f"pg_ctl failed: {control_log.read_text(encoding='utf-8')[-1500:]}")
            return ""
        result = subprocess.run([str(args.postgres_bin / (binary + suffix)), *map(str, arguments)],
                                env=env, capture_output=True, text=True, creationflags=flags, timeout=45)
        if result.returncode:
            raise RuntimeError(f"{binary} failed: {result.stderr[-1500:]}")
        return result.stdout.strip()

    with tempfile.TemporaryDirectory(prefix="migration-check-", dir=output) as temporary:
        scratch = Path(temporary).resolve()
        assert scratch.is_relative_to(output.resolve())
        data = scratch / ".pgdata"
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        run("initdb", "-D", data, "-A", "trust", "-U", "migration_test", "--no-locale", "--encoding=UTF8")
        started = False
        try:
            run("pg_ctl", "-D", data, "-l", scratch / "postgres.log", "-o", f"-h 127.0.0.1 -p {port} -F", "-w", "start")
            started = True
            def sql(query, database="postgres"):
                return run("psql", "-X", "-h", "127.0.0.1", "-p", port, "-U", "migration_test", "-d", database,
                           "-v", "ON_ERROR_STOP=1", "-At", "-c", query)

            def sql_file(path, database="postgres"):
                return run("psql", "-X", "-h", "127.0.0.1", "-p", port, "-U", "migration_test", "-d", database,
                           "-v", "ON_ERROR_STOP=1", "-q", "-f", path)

            schema_path = root / "supabase_schema.sql"
            migration_path = root / "backend/migrations/20261026_datasets_and_certificate_snapshots.sql"
            schema = schema_path.read_text(encoding="utf-8")
            old_schema = schema.split("-- Dataset and certificate snapshot upgrade", 1)[0] + "\nCOMMIT;"
            baseline = scratch / "baseline.sql"
            baseline.write_text(old_schema, encoding="utf-8")
            sql_file(baseline)
            sql("""
                INSERT INTO users(id,name,email,password_hash,role) VALUES(1,'Test admin','admin@example.com','inert','ADMIN');
                INSERT INTO participants(id,name,email,team_name,college) VALUES
                (101,'John','shared@example.com','Alpha','College, One'),
                (102,'Jonathan','shared@example.com','Beta','College Two');
                INSERT INTO certificate_templates(id,name,file_data,file_type,created_by) VALUES(1,'Original',decode('010203','hex'),'png',1);
                INSERT INTO email_campaigns(id,name,certificate_template_id,sender_name,subject,body,created_by,status)
                VALUES(1,'Historical',1,'Admin','Subject','Body',1,'COMPLETED');
                INSERT INTO email_deliveries(id,campaign_id,participant_id,participant_key,participant_name,college,email,status)
                VALUES(1,1,101,'participant:101','John','College, One','shared@example.com','SENT');
            """)
            history_query = "SELECT id,participant_id,participant_key,participant_name,email,status FROM email_deliveries ORDER BY id"
            before = sql(history_query)
            sql_file(migration_path)
            assert sql("SELECT count(*) FROM datasets WHERE is_legacy") == "1"
            assert sql("SELECT participant_id FROM dataset_participants ORDER BY participant_id") == "101\n102"
            assert sql(history_query) == before
            frozen_query = "SELECT certificate_snapshot::jsonb,encode(certificate_file_data,'hex') FROM email_campaigns WHERE id=1"
            frozen = sql(frozen_query)
            assert '"name": "Original"' in frozen and frozen.endswith("|010203")
            sql("UPDATE certificate_templates SET name='Later edit', name_font_size=80 WHERE id=1")
            sql("UPDATE email_deliveries SET team_name=NULL WHERE id=1")
            sql("UPDATE participants SET team_name='Later team' WHERE id=101")
            sql_file(migration_path)
            assert sql("SELECT count(*) FROM datasets") == "1"
            assert sql("SELECT count(*) FROM dataset_participants") == "2"
            assert sql("SELECT team_name IS NULL FROM email_deliveries WHERE id=1") == "t"
            assert sql(frozen_query) == frozen
            sql("""
                UPDATE email_campaigns SET dataset_id=(SELECT id FROM datasets LIMIT 1) WHERE id=1;
                DO $$ BEGIN
                    BEGIN
                        DELETE FROM datasets;
                        RAISE EXCEPTION 'Referenced dataset deletion must be restricted';
                    EXCEPTION WHEN integrity_constraint_violation THEN NULL;
                    END;
                END $$;
            """)
            sql("CREATE DATABASE fresh_check")
            sql_file(schema_path, "fresh_check")
            sql_file(schema_path, "fresh_check")
            assert sql("SELECT count(*) FROM datasets", "fresh_check") == "0"
            assert sql("SELECT count(*) FROM email_deliveries", "fresh_check") == "0"
            print("PostgreSQL migration checks passed: legacy data/IDs, shared-email memberships, snapshots, restricted deletion, repeat upgrade and fresh bootstrap.")
        finally:
            if started:
                run("pg_ctl", "-D", data, "-m", "fast", "-w", "stop")


if __name__ == "__main__":
    main()
