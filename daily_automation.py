#!/usr/bin/env python3
"""知星日报：全量更新、完整性校验、自动重试和 macOS 定时安装。"""
import argparse
import fcntl
import json
import os
import plistlib
import re
import signal
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parent
TIMEZONE = ZoneInfo('Asia/Shanghai')
LABEL = 'com.zhixing.dailyupdate'
START_HOUR, START_MINUTE = 12, 15
RETRY_MINUTES = 30


def now():
    return datetime.now(TIMEZONE)


def read_state(repo):
    path = repo / 'logs/daily_automation_state.json'
    return json.loads(path.read_text()) if path.exists() else {}


def write_state(repo, state):
    path = repo / 'logs/daily_automation_state.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n')
    temp.replace(path)


def should_run(state, instant):
    if (instant.hour, instant.minute) < (START_HOUR, START_MINUTE):
        return False
    if state.get('status') == 'success' and state.get('lastSuccessDate') == instant.date().isoformat():
        return False
    attempted = state.get('lastAttemptAt')
    if attempted and instant - datetime.fromisoformat(attempted) < timedelta(minutes=RETRY_MINUTES):
        return False
    return True


def validate_outputs(repo, target, started_at=None):
    """零订单/零注册允许存在；验证查询水位，不用用户数量假设当天必有数据。"""
    checks = {}

    def check(name, action):
        try:
            action()
            checks[name] = {'ok': True}
        except (OSError, ValueError, KeyError, TypeError, AssertionError) as error:
            checks[name] = {'ok': False, 'reason': str(error)}

    def require(condition, message):
        if not condition:
            raise ValueError(message)

    def load(name):
        return json.loads((repo / name).read_text())

    def fresh(name):
        if started_at:
            require((repo / name).stat().st_mtime >= started_at.timestamp() - 2,
                    f'{name} 本次未成功刷新')

    def overview():
        for name in ('index.html', 'dashboard.html'):
            match = re.search(r'const FALLBACK\s*=\s*(\[.*?\]);', (repo / name).read_text(), re.S)
            require(match is not None, f'{name} 缺少营销数据')
            days = {item['date'] for item in json.loads(match.group(1))}
            require(target in days, f'{target} 表 1 / 表 2 报表尚未完整，稍后自动补拉')

    def channel():
        data = load('channel_roi_data.json')
        require(data['endDate'] == target and data['availableEndDate'] >= target,
                f'渠道数据尚未覆盖 {target}')
        fresh('channel_roi_data.json')

    def risk():
        source = (repo / 'risk_daily_data.js').read_text()
        data, _ = json.JSONDecoder().raw_decode(source.split('=', 1)[1].lstrip())
        require(data['end'] == target, f'风控查询尚未覆盖 {target}')
        require(any(day['date'] == target and day.get('available') for day in data['days']),
                f'{target} 风控结果尚不可用')
        fresh('risk_daily_data.js')

    def attribution():
        pending = load('logs/attribution_pending.json')
        require(not pending, '归因待补拉日期：' + ', '.join(pending))
        require(isinstance(load('ad_users.json')['users'], list), '投放用户格式异常')
        fresh('logs/attribution_pending.json')

    def materials():
        data = load('materials.json')
        require(data['endDate'] == target and isinstance(data['list'], list), '素材查询日期或格式异常')
        fresh('materials.json')

    def users():
        require(isinstance(load('user_orders.json'), dict), '订单格式异常')
        for name in ('consultant_data.json', 'consultant_all_data.json'):
            require(isinstance(load(name)['daily'], dict), f'{name} 格式异常')
            fresh(name)

    def publication():
        result = subprocess.run(['git', 'ls-remote', '--exit-code', 'origin', 'refs/heads/main'],
                                cwd=repo, env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'},
                                capture_output=True, text=True, timeout=45)
        require(result.returncode == 0 and result.stdout.strip(), 'GitHub 远端验证失败，稍后自动重试')
        head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()
        require(result.stdout.split()[0] == head, '本地提交尚未全部发布')

    for name, action in [('营销总览', overview), ('渠道', channel), ('风控', risk),
                         ('投放归因', attribution), ('素材', materials), ('订单与顾问', users),
                         ('GitHub 发布', publication)]:
        try:
            check(name, action)
        except subprocess.SubprocessError:
            checks[name] = {'ok': False, 'reason': '检查超时或进程失败，稍后自动重试'}
    return checks


def run_update(repo=REPO, scheduled=False):
    log_dir = repo / 'logs'
    log_dir.mkdir(exist_ok=True)
    # 内核锁在退出/崩溃时自动释放；所有计划任务共用同一把锁。
    with (log_dir / 'daily_automation.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('已有完整更新正在运行，本次跳过。')
            return 0
        instant = now()
        state = read_state(repo)
        if scheduled and not should_run(state, instant):
            return 0
        target = (instant.date() - timedelta(days=1)).isoformat()
        state.update(lastAttemptAt=instant.isoformat(), targetDate=target, status='running')
        write_state(repo, state)
        env = {**os.environ, 'TZ': 'Asia/Shanghai', 'PYTHONUNBUFFERED': '1',
               'ZHIXING_DATA_END': target, 'GIT_TERMINAL_PROMPT': '0'}
        for key in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy'):
            env.pop(key, None)
        exit_code = 1
        failure = None
        try:
            with (log_dir / 'daily_automation.log').open('a', buffering=1) as output:
                output.write(f'\n[{instant.isoformat()}] 完整更新，目标 {target}\n')
                proc = subprocess.Popen(['/bin/bash', str(repo / 'daily_update.sh'), 'full'],
                                        cwd=repo, env=env, stdout=output, stderr=subprocess.STDOUT,
                                        start_new_session=True)
                try:
                    exit_code = proc.wait(timeout=5400)
                except BaseException:
                    os.killpg(proc.pid, signal.SIGTERM)
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(proc.pid, signal.SIGKILL)
                        proc.wait()
                    raise
            checks = validate_outputs(repo, target, instant)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            failure = str(error)
            checks = {'执行任务': {'ok': False, 'reason': failure}}
        completed = now()
        success = exit_code == 0 and all(item['ok'] for item in checks.values())
        state.update(status='success' if success else 'retry_pending', lastExitCode=exit_code,
                     lastFinishedAt=completed.isoformat(), checks=checks,
                     nextRetryAt=None if success else (completed + timedelta(minutes=RETRY_MINUTES)).isoformat())
        if success:
            state['lastSuccessDate'] = instant.date().isoformat()
            state['lastPublishedDataDate'] = target
        notify = (not success and scheduled and
                  state.get('lastNotificationDate') != instant.date().isoformat())
        if notify:
            state['lastNotificationDate'] = instant.date().isoformat()
        # 重试间隔从完成时算起，避免长任务一结束就再次启动。
        state['lastAttemptAt'] = completed.isoformat()
        write_state(repo, state)
        print(json.dumps(state, ensure_ascii=False, indent=2))
        if notify:
            try:
                subprocess.run(['/usr/bin/osascript', '-e',
                    'display notification "日报更新尚未完整，30 分钟后自动重试。详情见 logs/daily_automation_state.json。" with title "知星日报"'],
                    capture_output=True, timeout=10)
            except (OSError, subprocess.SubprocessError):
                pass
        return 0 if success else 1


def install(repo=REPO):
    """只有此命令会修改本机 LaunchAgent；不创建重复的 Codex 自动任务。"""
    agents = Path.home() / 'Library/LaunchAgents'
    agents.mkdir(parents=True, exist_ok=True)
    (repo / 'logs').mkdir(exist_ok=True)
    domain = f'gui/{os.getuid()}'
    for label in (LABEL, 'com.zhixing.publishretry', 'com.zhixing.datasync', 'com.zhixing.userdata'):
        subprocess.run(['launchctl', 'bootout', f'{domain}/{label}'], capture_output=True)
        if label != LABEL:
            subprocess.run(['launchctl', 'disable', f'{domain}/{label}'], check=True)
    plist = agents / f'{LABEL}.plist'
    if plist.exists():
        backup = repo / 'logs/dailyupdate.plist.before-automation'
        if not backup.exists():
            backup.write_bytes(plist.read_bytes())
    config = {
        'Label': LABEL,
        'ProgramArguments': [sys.executable, str(repo / 'daily_automation.py'), 'tick'],
        'WorkingDirectory': str(repo), 'RunAtLoad': True,
        'StartCalendarInterval': {'Hour': START_HOUR, 'Minute': START_MINUTE},
        'StartInterval': 900, 'ThrottleInterval': 60, 'ProcessType': 'Background',
        'EnvironmentVariables': {'TZ': 'Asia/Shanghai', 'PYTHONUNBUFFERED': '1',
                                 'PATH': '/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin'},
        'StandardOutPath': str(repo / 'logs/daily_automation.launchd.log'),
        'StandardErrorPath': str(repo / 'logs/daily_automation.launchd.err.log'),
    }
    with plist.open('wb') as output:
        plistlib.dump(config, output)
    subprocess.run(['launchctl', 'enable', f'{domain}/{LABEL}'], check=True)
    subprocess.run(['launchctl', 'bootstrap', domain, str(plist)], check=True)
    print('已启用：北京时间每天 12:15 全量更新；失败后每 30 分钟重试；登录后自动检查漏更。')
    print(f'任务状态：{repo / "logs/daily_automation_state.json"}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', nargs='?', default='run', choices=['run', 'tick', 'install', 'status', 'check'])
    args = parser.parse_args()
    if args.command == 'install':
        install()
    elif args.command == 'status':
        print(json.dumps({'schedule': '每天 12:15（Asia/Shanghai），失败后每 30 分钟重试',
                          'state': read_state(REPO)}, ensure_ascii=False, indent=2))
    elif args.command == 'check':
        checks = validate_outputs(REPO, (now().date() - timedelta(days=1)).isoformat())
        print(json.dumps(checks, ensure_ascii=False, indent=2))
        return 0 if all(item['ok'] for item in checks.values()) else 1
    else:
        return run_update(scheduled=args.command == 'tick')
    return 0


if __name__ == '__main__':
    sys.exit(main())
