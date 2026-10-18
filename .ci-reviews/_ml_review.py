"""Execute the real existing contributor source and regression tests, without a commit."""
import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
from _mm_common import run, junit, sha

def main():
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);a=p.parse_args()
    packet=Path(__file__).resolve().parent;spec=json.loads((packet/'ml-review.json').read_text())
    source=Path(a.source).resolve();proof=source.parent/'proof';proof.mkdir(exist_ok=True)
    def exact():
        assert run(['git','rev-parse','HEAD'],source).decode().strip()==spec['head']
        assert run(['git','status','--porcelain','--untracked-files=no'],source)==b''
        for name,digest in (spec['source_sha256']|spec['config_sha256']).items():assert sha((source/name).read_bytes())==digest
    exact()
    assert run(['git','rev-parse','HEAD^'],source).decode().strip()==spec['actual_parent']
    run(['uv','sync','--locked','--group','dev'],source)
    exact()
    baseline=(packet/'baseline-search_utils.py').read_bytes()
    assert sha(baseline)==spec['baseline_source_sha256']
    target=source/spec['files'][0];fixed=target.read_bytes()
    try:
        target.write_bytes(baseline)
        normal=['uv','run','--no-sync','pytest','tests/utils/test_search_utils.py::test_pagination','-q','--junitxml=../proof/ml-baseline-controls.xml']
        run(normal,source);baseline_controls=junit(proof/'ml-baseline-controls.xml',tests=11)
        red=['uv','run','--no-sync','pytest','tests/utils/test_search_utils.py::test_invalid_page_tokens','-q','--junitxml=../proof/ml-red.xml']
        output=run(red,source,expect=1).decode()
        red_result=junit(proof/'ml-red.xml',**spec['baseline_expected'])
        assert all(x in output for x in ['AttributeError','TypeError','OverflowError','ValueError'])
    finally:target.write_bytes(fixed)
    exact()
    for command in spec['test_commands']:run(command,source)
    green=junit(proof/'ml-fixed.xml',tests=14)
    controls=junit(proof/'ml-controls.xml',tests=11)
    owning=junit(proof/'ml-owning.xml')
    assert owning['tests']>200
    probe='import hashlib,json,pathlib,sys;import mlflow.utils.search_utils as m;p=pathlib.Path(m.__file__).resolve();e=pathlib.Path(sys.argv[1]).resolve()/"mlflow/utils/search_utils.py";assert p==e;print(json.dumps({"origin":str(p),"sha256":hashlib.sha256(p.read_bytes()).hexdigest(),"python":sys.version}))'
    run(['uv','run','--no-sync','python','-c',probe,str(source)],source)
    env={'UV_PROJECT_ENVIRONMENT':str(source.parent/'mlflow-hook-env')}
    run(['uv','run','--only-group','lint','pre-commit','install','--install-hooks','--hook-type','pre-commit','--hook-type','prepare-commit-msg'],source,extra_env=env)
    run(['uv','run','--only-group','lint','pre-commit','run','install-bin','-a','-v'],source,extra_env=env)
    run(['uv','run','--only-group','lint','pre-commit','run','--files',*spec['files']],source,extra_env=env)
    exact()
    print('OCT17E_ML_REVIEW='+json.dumps({'state':'passed actual existing contributor source review','head':spec['head'],'actual_parent':spec['actual_parent'],'reviewed_PR':26834,'contributor':spec['contributor'],'baseline':red_result,'baseline_controls':baseline_controls,'fixed':green,'controls':controls,'owning':owning,'normal_scoped_hooks_passed':True,'source_configuration_unchanged':True,'new_source_commits':0,'DCO_or_PR_creation_attempts':0}),flush=True)

if __name__=='__main__':main()
