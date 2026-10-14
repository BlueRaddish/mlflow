"""Run frozen native source checks; never uses an API, remote ref, or publication command."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import traceback
import xml.etree.ElementTree as ET


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def git_blob(raw):
    return hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def run(command, cwd, *, expect=0, extra_env=None, log_stdout=True):
    result = subprocess.run(command, cwd=cwd, env=dict(os.environ, **(extra_env or {})),
                            stdin=subprocess.DEVNULL, capture_output=True, timeout=2700)
    item = {'command': command, 'cwd': str(cwd), 'exit_code': result.returncode,
            'stdout': result.stdout.decode(errors='replace') if log_stdout else None,
            'stdout_sha256': sha(result.stdout), 'stdout_bytes': len(result.stdout),
            'stderr': result.stderr.decode(errors='replace')}
    print('MM_COMMAND=' + json.dumps(item), flush=True)
    assert result.returncode == expect, f'Unexpected command exit {result.returncode}: {command}'
    return result.stdout


def prove(source, spec, *, fixed, head):
    assert run(['git', 'rev-parse', 'HEAD'], source).decode().strip() == head
    files = {}
    for name in spec['files']:
        raw = (source / name).read_bytes()
        expected = spec['source_proof'][name] if fixed else spec['base_source'][name]
        assert sha(raw) == expected['canonical_LF_sha256'] and git_blob(raw) == expected['target_git_blob']
        files[name] = {'sha256': sha(raw), 'git_blob': git_blob(raw)}
    actual_config = {name: sha((source / name).read_bytes()) for name in spec['config_sha256']}
    assert actual_config == spec['config_sha256'], 'Source configuration changed.'
    patch = run(['git', 'diff', '--binary', '--full-index', '--no-ext-diff', '--no-textconv',
                 spec['base'], '--', *spec['files']], source, log_stdout=False)
    assert sha(patch) == (spec['patch_sha256'] if fixed else sha(b''))
    changed = run(['git', 'diff', '--name-only', spec['base']], source).decode().splitlines()
    assert set(changed) == (set(spec['files']) if fixed else set())
    proof = {'head': head, 'source': files, 'config_sha256': actual_config,
             'patch_sha256': sha(patch), 'source_and_config_integrity': True}
    print('MM_SOURCE_PROOF=' + json.dumps(proof), flush=True)
    return proof


def junit(path, *, failures=0, tests=None):
    root = ET.parse(path).getroot()
    cases = list(root.iter('testcase'))
    failed = [case for case in cases if case.find('failure') is not None]
    assert cases and len(failed) == failures
    assert not list(root.iter('error')) and not list(root.iter('skipped'))
    if tests is not None:
        assert len(cases) == tests
    value = {'tests': len(cases), 'failures': len(failed), 'errors': 0, 'skipped': 0,
             'failed_names': [case.attrib['name'] for case in failed]}
    print('MM_JUNIT=' + json.dumps(value), flush=True)
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--scope', required=True, choices=['ms-evening', 'ml-evening'])
    parser.add_argument('--phase', required=True, choices=['source-validation', 'personal-verification'])
    parser.add_argument('--source', required=True)
    args = parser.parse_args()
    packet = Path(__file__).resolve().parent
    spec = json.loads((packet / (args.scope + '.json')).read_text())
    assert spec['scope_id'] == args.scope
    assert args.phase != 'personal-verification' or args.scope == 'ms-evening'
    patch = packet / spec['patch_name']
    assert sha(patch.read_bytes()) == spec['patch_sha256']
    source = Path(args.source).resolve()
    proof_dir = source.parent / 'proof'
    proof_dir.mkdir(exist_ok=True)
    assert run(['git', 'status', '--porcelain', '--untracked-files=no'], source) == b''
    prove(source, spec, fixed=False, head=spec['base'])
    run(['git', 'switch', '-c', 'fix/oct13-evening-remote-' + args.scope], source)
    sdk = source / 'python' if args.scope == 'ms-evening' else source
    if args.scope == 'ms-evening':
        assert run(['uv', '--version'], source).decode().split()[:2] == ['uv', '0.12.23']
        run(['uv', 'run', 'poe', 'install'], sdk)
    else:
        os.environ['UV_EXCLUDE_NEWER'] = spec['resolution_cutoff']
        run(['uv', 'sync', '--group', 'dev'], sdk)
    lock = sdk / 'uv.lock'
    assert lock.is_file()
    initial_lock = sha(lock.read_bytes())
    run(['git', 'apply', '--check', str(patch)], source)
    run(['git', 'apply', str(patch)], source)
    prove(source, spec, fixed=True, head=spec['base'])
    if args.scope == 'ml-evening':
        run(spec['test_commands'][0], sdk)
    if args.phase == 'source-validation':
        if args.scope == 'ms-evening':
            original = run(['git', 'show', spec['base'] + ':' + spec['files'][0]], source, log_stdout=False)
            (source / spec['files'][0]).write_bytes(original)
            for example_command in spec['test_commands'][:-1]:
                run([*example_command[:-1], 'normal-control'], sdk)
                red = subprocess.run(example_command, cwd=sdk, stdin=subprocess.DEVNULL,
                                     capture_output=True, timeout=600)
                output = (red.stdout + red.stderr).decode(errors='replace')
                print('MM_DOC_BASELINE=' + json.dumps({'command': example_command,
                      'exit_code': red.returncode, 'output': output}), flush=True)
                assert red.returncode == 1 and "NameError: name 'updates' is not defined" in output
            run(['git', 'apply', str(patch)], source)
        else:
            original = run(['git', 'show', spec['base'] + ':' + spec['files'][0]], source, log_stdout=False)
            (source / spec['files'][0]).write_bytes(original)
            red_command = ['uv', 'run', '--no-sync', 'pytest', 'tests/utils/test_search_utils.py::test_invalid_page_tokens',
                           '-q', '--junitxml=../proof/ml-red.xml']
            run(red_command, sdk, expect=1)
            junit(proof_dir / 'ml-red.xml', failures=8, tests=13)
            run(['uv', 'run', '--no-sync', 'pytest', 'tests/utils/test_search_utils.py::test_pagination',
                 '-q', '--junitxml=../proof/ml-normal-control.xml'], sdk)
            junit(proof_dir / 'ml-normal-control.xml')
            run(['git', 'restore', '--source=' + spec['base'], '--', *spec['files']], source)
            run(['git', 'apply', str(patch)], source)
    prove(source, spec, fixed=True, head=spec['base'])
    exit_codes = []
    for command in spec['test_commands']:
        run(command, sdk)
        exit_codes.append(0)
    junit(proof_dir / ('ms-owning.xml' if args.scope == 'ms-evening' else 'ml-owning.xml'))
    assert sha(lock.read_bytes()) == initial_lock, 'Declared dependency resolution changed during tests.'
    prove(source, spec, fixed=True, head=spec['base'])
    if args.phase == 'personal-verification':
        # The job has no hook/commit/publication phase and no dependent jobs.
        print('OCT13_USER_VERIFY=' + json.dumps({'scope_id': args.scope, 'base_sha': spec['base'],
              'patch_sha256': spec['patch_sha256'], 'test_commands': spec['test_commands'],
              'exit_codes': exit_codes}), flush=True)
        return
    if args.scope == 'ms-evening':
        run(['uv', 'run', 'poe', 'prek-install'], sdk)
        run(['uv', 'run', '--group', 'tool-hooks', 'prek', 'run', '--files',
             'packages/core/agent_framework/_types.py'], sdk)
    else:
        hook_env = {'UV_PROJECT_ENVIRONMENT': str(source.parent / 'mlflow-hook-env')}
        run(['uv', 'run', '--only-group', 'lint', 'pre-commit', 'install', '--install-hooks',
             '--hook-type', 'pre-commit', '--hook-type', 'prepare-commit-msg'], sdk, extra_env=hook_env)
        run(['uv', 'run', '--only-group', 'lint', 'pre-commit', 'run', 'install-bin', '-a', '-v'], sdk, extra_env=hook_env)
        run(['uv', 'run', '--only-group', 'lint', 'pre-commit', 'run', '--files', *spec['files']], sdk, extra_env=hook_env)
    prove(source, spec, fixed=True, head=spec['base'])
    assert sha(lock.read_bytes()) == initial_lock, 'Normal hooks changed dependency resolution.'
    # Exact post-hook source/config/lock equality keeps the prior owning-test result applicable.
    if args.scope == 'ml-evening':
        print('MM_FINAL=' + json.dumps({'scope_id': args.scope, 'state': 'tests and normal scoped hooks passed; '
              'source commit withheld pending actual new DCO certification', 'signed_or_unsigned_source_commit': False}), flush=True)
        return
    run(['git', 'add', '--', *spec['files']], source)
    trace = proof_dir / 'ms-native-commit-trace.jsonl'
    env = {'GIT_AUTHOR_NAME': 'Jeeho Lee', 'GIT_AUTHOR_EMAIL': 'jeeholife2@gmail.com',
           'GIT_COMMITTER_NAME': 'Jeeho Lee', 'GIT_COMMITTER_EMAIL': 'jeeholife2@gmail.com',
           'GIT_AUTHOR_DATE': spec['commit_date'], 'GIT_COMMITTER_DATE': spec['commit_date'],
           'GIT_TRACE2_EVENT': str(trace)}
    run(['git', 'commit', '-m', spec['title']], source, extra_env=env)
    events = [json.loads(line) for line in trace.read_text().splitlines()]
    starts = [row for row in events if row.get('event') == 'child_start' and row.get('hook_name') == 'pre-commit']
    assert starts, 'No actual pre-commit hook invocation.'
    for start in starts:
        assert any(row.get('event') == 'child_exit' and row.get('child_id') == start['child_id']
                   and row.get('sid') == start.get('sid') and row.get('code') == 0 for row in events)
    assert run(['git', 'status', '--porcelain', '--untracked-files=no'], source) == b''
    head = run(['git', 'rev-parse', 'HEAD'], source).decode().strip()
    raw_commit = run(['git', 'cat-file', 'commit', head], source, log_stdout=False)
    assert hashlib.sha1(b'commit ' + str(len(raw_commit)).encode() + b'\0' + raw_commit).hexdigest() == head
    final = prove(source, spec, fixed=True, head=head)
    print('MM_NATIVE_COMMIT=' + json.dumps({'scope_id': args.scope, 'head': head,
          'tree': run(['git', 'rev-parse', 'HEAD^{tree}'], source).decode().strip(),
          'raw_commit_base64': base64.b64encode(raw_commit).decode(), 'normal_hook_events': events,
          'source_proof': final, 'lock_sha256': initial_lock}), flush=True)


if __name__ == '__main__':
    try:
        main()
    except BaseException:
        traceback.print_exc()
        raise
