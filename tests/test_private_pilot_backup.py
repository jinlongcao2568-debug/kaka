from __future__ import annotations

import io
import json
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

from runtime.private_pilot_backup import (
    REQUIRED_SCHEMA_REVISION,
    PostgresConnectionConfig,
    PrivatePilotBackupConfig,
    PrivatePilotBackupError,
    PrivatePilotRestoreConfig,
    create_private_pilot_backup,
    restore_private_pilot_backup_isolated,
    validate_private_pilot_backup,
    verify_object_storage_archive,
)


COUNTS = {
    "records": 7,
    "stage_states": 2,
    "work_items": 3,
    "operator_actions": 1,
    "worker_queue_items": 4,
    "worker_queue_events": 9,
}


class _FakePostgresTools:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def __call__(
        self,
        args: list[str],
        *,
        env: dict[str, str],
        capture_output: bool,
        text: bool,
        timeout: int,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(
            {
                "args": list(args),
                "env": dict(env),
                "capture_output": capture_output,
                "text": text,
                "timeout": timeout,
                "check": check,
            }
        )
        if args[0] == "pg_dump":
            dump_path = Path(args[args.index("--file") + 1])
            dump_path.write_bytes(b"controlled-postgresql-custom-dump")
            stdout = ""
        elif args[0] == "pg_restore":
            stdout = ""
        elif "SELECT version_num" in args[-1]:
            stdout = REQUIRED_SCHEMA_REVISION + "\n"
        else:
            stdout = json.dumps(COUNTS) + "\n"
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")


class PrivatePilotBackupTests(unittest.TestCase):
    def _postgres(self, root: Path, *, database: str) -> PostgresConnectionConfig:
        password_file = root / f"{database}.password"
        password_file.write_text("private-pilot-password-that-is-not-logged\n", encoding="utf-8")
        return PostgresConnectionConfig(
            host="postgres",
            port=5432,
            user="kaka",
            database=database,
            password_file=password_file,
        )

    def test_database_and_object_backup_then_isolated_restore_records_rpo_rto(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            objects = root / "source-objects"
            backups = root / "backups"
            target_objects = root / "restore-objects"
            reports = root / "restore-reports"
            (objects / "objects" / "aa").mkdir(parents=True)
            (objects / "objects" / "aa" / "artifact.bin").write_bytes(b"evidence-bytes")
            (objects / "snapshots").mkdir()
            (objects / "snapshots" / "manifest.json").write_text(
                '{"snapshot_id":"SNAP-1"}', encoding="utf-8"
            )
            runner = _FakePostgresTools()
            backup_config = PrivatePilotBackupConfig(
                tenant_id="customer-a",
                instance_id="primary",
                postgres=self._postgres(root, database="customer-a-primary"),
                object_storage_root=objects,
                backup_root=backups,
                backup_id="BACKUP-CONTROLLED-1",
                writers_paused_ack="WRITERS_PAUSED:customer-a-primary",
                schedule_interval_seconds=300,
                rpo_target_seconds=600,
            )

            manifest = create_private_pilot_backup(backup_config, runner=runner)
            validated = validate_private_pilot_backup(backups / "BACKUP-CONTROLLED-1")
            restore_config = PrivatePilotRestoreConfig(
                backup_root=backups,
                backup_id="BACKUP-CONTROLLED-1",
                source_database_name="customer-a-primary",
                target_postgres=self._postgres(
                    root,
                    database="customer-a-primary-restore-drill",
                ),
                target_object_parent=target_objects,
                report_root=reports,
                isolated_ack="RESTORE_ISOLATED:customer-a-primary-restore-drill",
                rto_target_seconds=600,
            )
            report = restore_private_pilot_backup_isolated(restore_config, runner=runner)

            self.assertEqual(validated["backup_state"], "COMPLETE")
            self.assertEqual(validated["database_record_counts"], COUNTS)
            self.assertTrue(manifest["rpo"]["target_met_by_estimate"])
            self.assertTrue(manifest["consistency"]["operator_writers_paused_acknowledged"])
            self.assertEqual(report["restore_state"], "VALIDATED_ISOLATED_RESTORE")
            self.assertTrue(report["rto"]["target_met"])
            self.assertFalse(report["active_database_mutated"])
            self.assertFalse(report["active_object_storage_mutated"])
            restored_root = target_objects / "BACKUP-CONTROLLED-1"
            self.assertEqual(
                (restored_root / "objects" / "aa" / "artifact.bin").read_bytes(),
                b"evidence-bytes",
            )
            self.assertTrue(Path(report["report_path"]).is_file())
            commands = [str(item) for call in runner.calls for item in call["args"]]
            self.assertIn("pg_dump", commands)
            self.assertIn("pg_restore", commands)
            self.assertNotIn("private-pilot-password-that-is-not-logged", " ".join(commands))
            for call in runner.calls:
                self.assertNotIn("PGPASSWORD", call["env"])
                self.assertIn("PGPASSFILE", call["env"])

    def test_manifest_tamper_archive_traversal_and_active_target_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            objects = root / "source-objects"
            backups = root / "backups"
            objects.mkdir()
            (objects / "one.bin").write_bytes(b"one")
            postgres = self._postgres(root, database="customer-a-primary")

            with self.assertRaisesRegex(PrivatePilotBackupError, "writers-paused"):
                PrivatePilotBackupConfig(
                    tenant_id="customer-a",
                    instance_id="primary",
                    postgres=postgres,
                    object_storage_root=objects,
                    backup_root=backups,
                    backup_id="BACKUP-CONTROLLED-2",
                    writers_paused_ack="WRONG",
                )

            config = PrivatePilotBackupConfig(
                tenant_id="customer-a",
                instance_id="primary",
                postgres=postgres,
                object_storage_root=objects,
                backup_root=backups,
                backup_id="BACKUP-CONTROLLED-2",
                writers_paused_ack="WRITERS_PAUSED:customer-a-primary",
            )
            create_private_pilot_backup(config, runner=_FakePostgresTools())
            dump_path = backups / config.backup_id / "database.dump"
            dump_path.write_bytes(dump_path.read_bytes() + b"tampered")
            with self.assertRaisesRegex(PrivatePilotBackupError, "size mismatch"):
                validate_private_pilot_backup(backups / config.backup_id)

            with self.assertRaisesRegex(PrivatePilotBackupError, "must differ"):
                PrivatePilotRestoreConfig(
                    backup_root=backups,
                    backup_id=config.backup_id,
                    source_database_name="customer-a-primary",
                    target_postgres=postgres,
                    target_object_parent=root / "target",
                    report_root=root / "reports",
                    isolated_ack="RESTORE_ISOLATED:customer-a-primary",
                )

            evil_archive = root / "evil.tar.gz"
            inventory = root / "evil-inventory.jsonl"
            inventory.write_text(
                json.dumps(
                    {
                        "path": "safe.txt",
                        "byte_size": 1,
                        "sha256": "2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            with tarfile.open(evil_archive, "w:gz") as archive:
                info = tarfile.TarInfo("../escape.txt")
                info.size = 1
                archive.addfile(info, io.BytesIO(b"x"))
            with self.assertRaisesRegex(PrivatePilotBackupError, "unsafe path"):
                verify_object_storage_archive(evil_archive, inventory_path=inventory)

            injected_password = root / "injected.password"
            injected_password.write_text(
                "valid-password-value\npostgres:5432:other:user:injected",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(PrivatePilotBackupError, "invalid character"):
                PostgresConnectionConfig(
                    host="postgres",
                    port=5432,
                    user="kaka",
                    database="customer-a-primary",
                    password_file=injected_password,
                )


if __name__ == "__main__":
    unittest.main()
