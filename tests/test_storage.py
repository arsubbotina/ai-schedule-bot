"""Offline checks for actual storage functions, without importing API clients."""
import ast
import logging
from pathlib import Path
import sqlite3
import tempfile
from typing import Dict, List
import unittest

class StorageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        tree = ast.parse((Path(__file__).resolve().parents[1] / 'bot.py').read_text())
        wanted = {'init_db', 'add_schedule_item', 'get_schedule_for_day'}
        module = ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in wanted], type_ignores=[])
        self.scope = {'sqlite3': sqlite3, 'DB_PATH': str(Path(self.tmp.name)/'test.db'), 'logger': logging.getLogger('test'), 'List': List, 'Dict': Dict}
        exec(compile(module, 'bot.py', 'exec'), self.scope)
        self.scope['init_db']()

    def test_restart_preserves_schedule(self):
        self.assertTrue(self.scope['add_schedule_item'](1, 'понедельник', '09:00', '10:00', 'Математика', 'лекция'))
        self.scope['init_db']()
        rows = self.scope['get_schedule_for_day'](1, 'понедельник')
        self.assertEqual([x['subject_name'] for x in rows], ['Математика'])

    def test_users_are_separate_and_time_is_sorted(self):
        for user, time in [(1,'12:00'), (2,'08:00'), (1,'09:00')]:
            self.assertTrue(self.scope['add_schedule_item'](user, 'понедельник', time, '13:00', 'Курс', 'лекция'))
        self.assertEqual([x['start_time'] for x in self.scope['get_schedule_for_day'](1,'понедельник')], ['09:00','12:00'])
        self.assertEqual(len(self.scope['get_schedule_for_day'](2,'понедельник')), 1)

if __name__ == '__main__':
    unittest.main()
