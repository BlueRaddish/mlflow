"""Strict existing-source proof; configuration-only control has no publication path."""
import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from _mm_common import run, junit, sha

p = argparse.ArgumentParser()
p.add_argument('--source', required=True)
a = p.parse_args()
control = Path(__file__).resolve().parent
spec = json.loads((control / 'review.json').read_text())
source = Path(a.source).resolve()
sdk = source / 'python' if spec['label'] == 'ms' else source
proof = source.parent / 'proof'
proof.mkdir()
record = {'head': spec['head'], 'reviewed_PR': spec['reviewed_PR'], 'new_source_commits': 0,
          'PR_creation_attempts': 0, 'personal_verification_claimed': False, 'state': 'pending'}


def exact():
    assert run(['git', 'rev-parse', 'HEAD'], source).decode().strip() == spec['head']
    assert run(['git', 'rev-parse', 'HEAD^'], source).decode().strip() == spec['actual_parent']
    assert run(['git', 'status', '--porcelain', '--untracked-files=no'], source) == b''
    for name, digest in (spec['source_sha256'] | spec['config_sha256']).items():
        assert sha((source / name).read_bytes()) == digest, name


def check(label, args, expect=0):
    return run(['uv', 'run', '--frozen', '--no-sync', 'pytest', *args, '-q',
                '--junitxml=' + str(proof / (label + '.xml'))], sdk, expect=expect)


try:
    exact()
    if spec['label'] == 'ms':
        run(['uv', 'run', '--frozen', 'poe', 'install'], sdk)
    else:
        run(['uv', 'sync', '--locked', '--group', 'dev'], sdk)
    exact()
    test = str(control / '_probe.py')
    target = source / spec['production']
    fixed = target.read_bytes()
    baseline = (control / 'baseline-production.py').read_bytes()
    assert sha(baseline) == spec['baseline_source_sha256']
    try:
        target.write_bytes(baseline)
        output = check('baseline', [test], expect=1).decode()
        record['baseline'] = junit(proof / 'baseline.xml', **spec['baseline_expected'])
        failed = [x for x in ET.parse(proof / 'baseline.xml').iter('testcase') if x.find('failure') is not None]
        assert all(spec['failed_name_contains'] in x.attrib['name'] for x in failed)
        assert all(spec['failed_message_contains'] in x.find('failure').text for x in failed)
        assert not any(x in output for x in ['ERROR collecting', 'ImportError:', 'ModuleNotFoundError:'])
    finally:
        target.write_bytes(fixed)
    exact()
    check('fixed', [test])
    record['fixed'] = junit(proof / 'fixed.xml', tests=spec['baseline_expected']['tests'])
    for label, args in spec['owning_tests'].items():
        check(label, args)
        record[label] = junit(proof / (label + '.xml'))
        assert record[label]['tests'] >= spec['owning_minimum'][label]
    probe = ('import hashlib,json,pathlib,sys;import ' + spec['module'] + ' as m;'
             'p=pathlib.Path(m.__file__).resolve();e=pathlib.Path(sys.argv[1]).resolve();assert p==e;'
             'assert hashlib.sha256(p.read_bytes()).hexdigest()==sys.argv[2];'
             'print(json.dumps({"origin":str(p),"python":sys.version}))')
    run(['uv', 'run', '--frozen', '--no-sync', 'python', '-c', probe, str(target),
         spec['source_sha256'][spec['production']]], sdk)
    exact()
    if spec['label'] == 'ms':
        run(['uv', 'run', '--frozen', 'poe', 'prek-install'], sdk)
        run(['uv', 'run', '--frozen', '--group', 'tool-hooks', 'prek', 'run', '--files',
             *[x.removeprefix('python/') for x in spec['files']]], sdk)
    else:
        env = {'UV_PROJECT_ENVIRONMENT': str(source.parent / 'mlflow-hook-env')}
        run(['uv', 'run', '--only-group', 'lint', 'pre-commit', 'install', '--install-hooks',
             '--hook-type', 'pre-commit', '--hook-type', 'prepare-commit-msg'], sdk, extra_env=env)
        run(['uv', 'run', '--only-group', 'lint', 'pre-commit', 'run', 'install-bin', '-a', '-v'], sdk, extra_env=env)
        run(['uv', 'run', '--only-group', 'lint', 'pre-commit', 'run', '--files', *spec['files']], sdk, extra_env=env)
    exact()
    record.update(state='passed actual independent regressions, owning tests and normal scoped hooks',
                  source_configuration_unchanged=True, normal_scoped_hooks_passed=True)
except BaseException as error:
    record.update(state='failed_or_partial', error=repr(error))
    raise
finally:
    print('OCT18E_MM_REVIEW=' + json.dumps(record), flush=True)
