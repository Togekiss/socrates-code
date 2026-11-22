"""
Deprecated compatibility shim for legacy db.migrate callers.
Delegates test seeding to tests.seed_test_backup and legacy migration to deprecated.migrate.
"""

from typing import Any, Dict
import warnings


def migrate_single_backup(
    backup: dict,
    dry_run: bool = False,
    skip_snapshots: bool = False,
) -> Dict[str, Any]:
    """Deprecated compatibility wrapper delegating to tests.seed_test_backup or deprecated.migrate."""
    warnings.warn(
        "db.migrate is deprecated; use tests.seed_test_backup for tests.",
        DeprecationWarning,
        stacklevel=2,
    )
    if not dry_run:
        try:
            from tests.seed_test_backup import seed_test_backup
            return seed_test_backup(
                backup_id=str(backup["backup_id"]),
                backup=backup,
                skip_snapshots=skip_snapshots,
            )
        except ImportError:
            pass
    from deprecated.migrate import migrate_single_backup as _legacy_migrate_single_backup
    return _legacy_migrate_single_backup(backup, dry_run=dry_run, skip_snapshots=skip_snapshots)


def migrate_for_tests(backup_id: str) -> Dict[str, Any]:
    """Deprecated compatibility wrapper delegating to tests.seed_test_backup.seed_test_backup."""
    warnings.warn(
        "db.migrate.migrate_for_tests is deprecated; use tests.seed_test_backup.seed_test_backup.",
        DeprecationWarning,
        stacklevel=2,
    )
    from tests.seed_test_backup import seed_test_backup
    return seed_test_backup(backup_id=str(backup_id), skip_snapshots=True)
