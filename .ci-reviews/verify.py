"""Observe original/fixed source through real Windows APIs, plus ordinary Linux owner/hooks."""
import argparse,base64,json,os,sys
from pathlib import Path
from _mm_common import run,junit,sha
p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--mode',choices=['windows','quality'],required=True);a=p.parse_args()
v=Path(__file__).resolve().parent;s=json.loads((v/'spec.json').read_text());c=Path(a.source).resolve();proof=c.parent/'proof';proof.mkdir()
record={'state':'pending','mode':a.mode,'head':s['head'],'new_source_commits':0,'PR_creation_attempts':0,'no_encoding_or_IO_mocks':True}
def git(*args):return run(['git',*args],c)
def exact():
 assert git('rev-parse','HEAD').decode().strip()==s['head'] and git('rev-parse','HEAD^').decode().strip()==s['actual_parent']
 assert not git('status','--porcelain','--untracked-files=no').strip()
 assert {n:sha((c/n).read_bytes())for n in s['source_sha256']}==s['source_sha256']
 assert {n:sha((c/n).read_bytes())for n in s['config_sha256']}==s['config_sha256']
def tests(label,args,failures=0,count=None):
 output=run(['uv','run','--python','3.11','--frozen','--no-sync','pytest',*args,'-q','--junitxml='+str(proof/(label+'.xml'))],c,expect=1 if failures else 0)
 value=junit(proof/(label+'.xml'),failures=failures,tests=count)
 if failures:assert b'ERROR collecting' not in output and b'ImportError:' not in output
 return value
try:
 exact();run(['uv','sync','--locked','--group','dev','--python','3.11'],c);exact()
 code='import hashlib,sys,json,locale;from pathlib import Path;import mlflow.models.model_config as m;p=Path(m.__file__).resolve();assert p==Path(sys.argv[1]).resolve();print(json.dumps({"python":sys.version,"platform":sys.platform,"utf8_mode":sys.flags.utf8_mode,"default_encoding":locale.getencoding(),"origin":str(p)}))'
 record['actual_origin']=json.loads(run(['uv','run','--python','3.11','--frozen','--no-sync','python','-c',code,str(c/s['production'][0])],c))
 if a.mode=='windows':assert record['actual_origin']['platform']=='win32' and record['actual_origin']['utf8_mode']==0 and record['actual_origin']['default_encoding'].lower()=='cp1252'
 record['callers']=git('grep','-n','_log_v2(','--','mlflow').decode()
 if a.mode=='windows':
  record['fixed']=tests('fixed',[str(v/'consumer.py')],count=13)
  originals={n:(c/n).read_bytes()for n in s['production']}
  for label,indices,failures in [('all_parent',[0,1,2],10),('only_model_parent',[2],4)]:
   try:
    for i in indices:
     n=s['production'][i];b=(v/f'baseline-{i}.py').read_bytes();assert sha(b)==s['baseline_sha256'][n];(c/n).write_bytes(b)
    record[label]=tests(label,[str(v/'consumer.py')],failures=failures,count=13)
   finally:
    for n,b in originals.items():(c/n).write_bytes(b)
   exact()
 record['owners']=tests('owners',['tests/models/test_model_config.py'])
 if a.mode=='quality':
  env={'UV_PROJECT_ENVIRONMENT':str(c.parent/'hook-env')}
  for command in [['uv','run','--only-group','lint','pre-commit','install','--install-hooks','--hook-type','pre-commit','--hook-type','prepare-commit-msg'],['uv','run','--only-group','lint','pre-commit','run','install-bin','-a','-v']]:run(command,c,extra_env=env)
  try:
   output=run(['uv','run','--only-group','lint','pre-commit','run','--files',*s['files']],c,extra_env=env)
   record['normal_scoped_hooks_passed']=True;record['hook_skips']=output.decode().count('Skipped')
  finally:
   delta=git('diff','--full-index','--binary');record['post_hook_diff_base64']=base64.b64encode(delta).decode();print('OCT22_ML_HOOK_DIFF='+record['post_hook_diff_base64'],flush=True)
 exact();record['state']='passed actual '+a.mode+' checks'
except BaseException as error:record.update(state='failed_or_partial',error=repr(error));raise
finally:print('OCT22_ML_RESULT='+json.dumps(record),flush=True)
