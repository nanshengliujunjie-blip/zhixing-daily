"""运行：python3 -m unittest -v test_daily_automation.py。无网络/真实定时任务写入。"""
import contextlib
import fcntl
import io
import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import daily_automation as automation


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        self.time = datetime(2026, 10, 27, 12, 15, tzinfo=automation.TIMEZONE)

    def test_starts_at_1215_and_catches_up(self):
        self.assertFalse(automation.should_run({}, self.time - timedelta(minutes=1)))
        self.assertTrue(automation.should_run({}, self.time))
        self.assertTrue(automation.should_run({}, self.time + timedelta(hours=7)))

    def test_success_stops_for_today_but_not_tomorrow(self):
        state = {'lastSuccessDate': '2026-10-27', 'status': 'success'}
        self.assertFalse(automation.should_run(state, self.time))
        self.assertTrue(automation.should_run(state, self.time + timedelta(days=1)))

    def test_partial_and_failed_manual_runs_retry_after_30_minutes(self):
        state = {'lastSuccessDate': '2026-10-27', 'status': 'retry_pending',
                 'lastAttemptAt': self.time.isoformat()}
        self.assertFalse(automation.should_run(state, self.time + timedelta(minutes=29)))
        self.assertTrue(automation.should_run(state, self.time + timedelta(minutes=30)))


class CompletenessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        self.target = '2026-10-26'
        (self.repo / 'logs').mkdir()
        for name in ['index.html', 'dashboard.html']:
            (self.repo / name).write_text('const FALLBACK = [{"date":"2026-10-26"}];')
        self.put('channel_roi_data.json', {'endDate': self.target, 'availableEndDate': self.target})
        risk = {'end': self.target, 'days': [{'date': self.target, 'available': True}]}
        (self.repo / 'risk_daily_data.js').write_text('const RISK_DAILY = ' + json.dumps(risk) + ';')
        self.put('logs/attribution_pending.json', [])
        self.put('ad_users.json', {'users': []})
        self.put('materials.json', {'endDate': self.target, 'list': []})
        self.put('user_orders.json', {})
        for name in ['consultant_data.json', 'consultant_all_data.json']:
            self.put(name, {'daily': {}})

    def tearDown(self):
        self.temp.cleanup()

    def put(self, name, data):
        (self.repo / name).write_text(json.dumps(data))

    def validate(self):
        with patch.object(automation.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'abc\trefs/heads/main\n', '')), \
             patch.object(automation.subprocess, 'check_output', return_value='abc\n'):
            return automation.validate_outputs(self.repo, self.target)

    def test_empty_activity_is_valid_if_queries_completed(self):
        self.assertTrue(all(result['ok'] for result in self.validate().values()))

    def test_delayed_table1_is_incomplete_even_after_successful_push(self):
        (self.repo / 'index.html').write_text('const FALLBACK = [{"date":"2026-10-25"}];')
        checks = self.validate()
        self.assertFalse(checks['营销总览']['ok'])
        self.assertTrue(checks['GitHub 发布']['ok'])

    def test_attribution_holes_are_not_hidden_by_newer_data(self):
        self.put('logs/attribution_pending.json', ['2026-10-21'])
        self.assertFalse(self.validate()['投放归因']['ok'])

    def test_unavailable_risk_day_is_incomplete(self):
        (self.repo / 'risk_daily_data.js').write_text('const RISK_DAILY = ' + json.dumps(
            {'end': self.target, 'days': [{'date': self.target, 'available': False}]}))
        self.assertFalse(self.validate()['风控']['ok'])

    def test_old_generated_files_cannot_pass_a_new_run(self):
        old = self.repo / 'channel_roi_data.json'
        os.utime(old, (1, 1))
        with patch.object(automation.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'abc\trefs/heads/main\n', '')), \
             patch.object(automation.subprocess, 'check_output', return_value='abc\n'):
            checks = automation.validate_outputs(self.repo, self.target, automation.now() - timedelta(seconds=5))
        self.assertFalse(checks['渠道']['ok'])


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        (self.repo / 'logs').mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def test_overlap_is_skipped(self):
        with (self.repo / 'logs/daily_automation.lock').open('a') as lock, \
             patch.object(automation.subprocess, 'Popen') as spawn, contextlib.redirect_stdout(io.StringIO()):
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(automation.run_update(self.repo), 0)
            spawn.assert_not_called()

    def run_fake(self, code, valid):
        process = MagicMock()
        process.wait.return_value = code
        checks = {'营销总览': {'ok': valid}}
        with patch.object(automation.subprocess, 'Popen', return_value=process) as spawn, \
             patch.object(automation, 'validate_outputs', return_value=checks), \
             contextlib.redirect_stdout(io.StringIO()):
            result = automation.run_update(self.repo)
        self.assertEqual(spawn.call_args.kwargs['env']['ZHIXING_DATA_END'],
                         (automation.now().date() - timedelta(days=1)).isoformat())
        return result, automation.read_state(self.repo)

    def test_child_success_with_missing_data_still_retries(self):
        code, state = self.run_fake(0, False)
        self.assertEqual(code, 1)
        self.assertEqual(state['status'], 'retry_pending')
        self.assertNotIn('lastSuccessDate', state)
        self.assertTrue(state['nextRetryAt'])

    def test_failed_child_with_valid_old_files_still_retries(self):
        code, state = self.run_fake(1, True)
        self.assertEqual(code, 1)
        self.assertEqual(state['status'], 'retry_pending')

    def test_success_records_published_date(self):
        code, state = self.run_fake(0, True)
        self.assertEqual(code, 0)
        self.assertEqual(state['lastPublishedDataDate'], state['targetDate'])
        self.assertIsNone(state['nextRetryAt'])


if __name__ == '__main__':
    unittest.main()
