"""Updater inspection/backup tests; never connects to a database or printer."""

import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from print_platform.deployment import update_check


class DeploymentTests(unittest.TestCase):
    def run_check(self, root, count=0, dump=False, returncode=0):
        connection = MagicMock()
        connection.execute.return_value.scalar_one.return_value = count
        database = MagicMock()
        database.connect.return_value.__enter__.return_value = connection
        output = StringIO()
        destination = Path(root) / 'database.dump'

        def backup(arguments, **kwargs):
            self.assertNotIn('secret', ' '.join(arguments))
            self.assertEqual(kwargs['env']['PGPASSWORD'], 'secret')
            self.assertIn('sslmode=require', arguments[-1])
            if not returncode:
                destination.write_bytes(b'PGDMP fixture')
            return SimpleNamespace(returncode=returncode)

        with (
            patch('print_platform.deployment.engine', return_value=database),
            patch('print_platform.deployment.config', return_value=SimpleNamespace(storage=SimpleNamespace(root='var/storage'))),
            patch.dict(os.environ, {'PLATFORM_DATABASE_URL': 'postgresql+psycopg://user:secret@localhost:5432/test?sslmode=require'}),
            patch('print_platform.deployment.subprocess.run', side_effect=backup) as process,
            redirect_stdout(output),
        ):
            update_check(root, str(destination) if dump else None)
        self.assertEqual(process.call_count, int(dump))
        return json.loads(output.getvalue())

    def test_storage_uses_installation_not_staging_directory(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(self.run_check(root)['storage_path'], str((Path(root) / 'var/storage').resolve()))

    def test_inflight_tasks_block_update(self):
        with tempfile.TemporaryDirectory() as root, self.assertRaisesRegex(RuntimeError, '任务'):
            self.run_check(root, count=1, dump=True)

    def test_backup_keeps_password_out_of_command_line(self):
        with tempfile.TemporaryDirectory() as root:
            self.run_check(root, dump=True)

    def test_failed_backup_blocks_update(self):
        with tempfile.TemporaryDirectory() as root, self.assertRaisesRegex(RuntimeError, '备份失败'):
            self.run_check(root, dump=True, returncode=1)


if __name__ == '__main__':
    unittest.main()
