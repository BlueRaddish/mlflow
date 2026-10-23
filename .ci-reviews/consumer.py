"""Native Windows consuming probes; no patched open, locale or I/O functions."""
import json,locale,os,sys
from pathlib import Path
import pytest
import mlflow
from mlflow.models import ModelConfig,Model
from mlflow.utils.model_utils import _validate_and_get_model_config_from_file
assert sys.platform=='win32' and sys.version_info[:2]==(3,11)
assert sys.flags.utf8_mode==0 and locale.getencoding().lower()=='cp1252'
PROMPTS=['You’re a helpful assistant — reply in 日本語','请提供简短的回答']
print('OCT22_ML_NATIVE_PLATFORM='+json.dumps({'platform':sys.platform,'python':sys.version,'utf8_mode':sys.flags.utf8_mode,'default_encoding':locale.getencoding(),'open_patch':False}),flush=True)
def config(tmp_path,prompt,extension):
 p=tmp_path/('config.'+extension)
 p.write_text(json.dumps({'system_prompt':prompt},ensure_ascii=False) if extension=='json' else 'system_prompt: '+json.dumps(prompt,ensure_ascii=False)+'\n',encoding='utf-8')
 return p
def echo():
 class Echo(mlflow.pyfunc.PythonModel):
  def predict(self,context,model_input,params=None):return [context.model_config['system_prompt']]
 return Echo()
def logged(tmp_path,prompt,extension,legacy=False,as_dict=False):
 uri='sqlite:///'+(tmp_path/'tracking.db').as_posix()
 mlflow.set_tracking_uri(uri)
 mlflow.set_experiment('native-encoding')
 payload={'system_prompt':prompt} if as_dict else str(config(tmp_path,prompt,extension))
 with mlflow.start_run() as run:
  if legacy:
   info=Model._log_v2(artifact_path='model',flavor=mlflow.pyfunc,python_model=echo(),model_config=payload,pip_requirements=[],signature=False)
  else:info=mlflow.pyfunc.log_model(name='model',python_model=echo(),model_config=payload,pip_requirements=[],signature=False)
  actual=mlflow.MlflowClient().get_run(run.info.run_id).data.params
  assert actual['system_prompt']==prompt
 loaded=mlflow.pyfunc.load_model(info.model_uri)
 assert loaded.predict([0])==[prompt]
 assert loaded._model_impl.context.model_config['system_prompt']==prompt
 return info
@pytest.mark.parametrize('prompt',PROMPTS)
def test_public_model_config_native_codec_preserves_prompt(tmp_path,prompt):
 p=config(tmp_path,prompt,'yaml')
 assert ModelConfig(development_config=str(p)).get('system_prompt')==prompt
@pytest.mark.parametrize('prompt',PROMPTS)
def test_config_helper_native_codec_preserves_prompt(tmp_path,prompt):
 p=config(tmp_path,prompt,'yml')
 assert _validate_and_get_model_config_from_file(str(p))=={'system_prompt':prompt}
@pytest.mark.parametrize('prompt',PROMPTS)
@pytest.mark.parametrize('extension',['yaml','json'])
def test_public_log_reload_and_logged_params_native_codec(tmp_path,prompt,extension):
 logged(tmp_path,prompt,extension)
@pytest.mark.parametrize('prompt',PROMPTS)
def test_supplemental_legacy_real_log_reload_and_params(tmp_path,prompt):
 logged(tmp_path,prompt,'json',legacy=True)
def test_ascii_file_control(tmp_path):
 assert ModelConfig(development_config=str(config(tmp_path,'plain ASCII','yaml'))).get('system_prompt')=='plain ASCII'
def test_unicode_dict_control():
 assert ModelConfig(development_config={'system_prompt':PROMPTS[0]}).get('system_prompt')==PROMPTS[0]
def test_public_unicode_dict_logging_control(tmp_path):
 logged(tmp_path,PROMPTS[0],'json',as_dict=True)
