"""Exercise both actual SQLite store modes across real three-page results."""
from contextlib import nullcontext
import pytest
from mlflow.exceptions import MlflowException
from mlflow.store.tracking.sqlalchemy_store import SqlAlchemyStore
from mlflow.store.tracking.sqlalchemy_workspace_store import WorkspaceAwareSqlAlchemyStore
from mlflow.utils.workspace_context import WorkspaceContext
from mlflow.utils.workspace_utils import DEFAULT_WORKSPACE_NAME


@pytest.fixture(params=[False, True], ids=['workspace-disabled', 'workspace-enabled'])
def store(tmp_path, monkeypatch, request):
    enabled = request.param
    monkeypatch.setenv('MLFLOW_ENABLE_WORKSPACES', 'true' if enabled else 'false')
    cls = WorkspaceAwareSqlAlchemyStore if enabled else SqlAlchemyStore
    artifacts = tmp_path / 'artifacts'
    artifacts.mkdir()
    with WorkspaceContext(DEFAULT_WORKSPACE_NAME) if enabled else nullcontext():
        value = cls('sqlite:///' + str(tmp_path / 'data.db'), artifacts.as_uri())
        experiment = value.create_experiment('pagination-review')
        models = [value.create_logged_model(experiment_id=experiment, name=f'm{i}') for i in range(5)]
        yield value, experiment, models


def collect(store, filter_string, order_by):
    value, experiment, expected = store
    ids, sizes, token = [], [], None
    for page_index in range(3):
        page = value.search_logged_models([experiment], filter_string=filter_string,
                                         order_by=order_by, max_results=2, page_token=token)
        sizes.append(len(page))
        ids.extend(x.model_id for x in page)
        token = page.token
        assert (token is not None) == (page_index < 2)
    assert sizes == [2, 2, 1]
    assert len(set(ids)) == 5 and set(ids) == {x.model_id for x in expected}
    return ids


@pytest.mark.parametrize(('filter_string', 'order_by'), [
    ('', None), (None, []), ('', []),
    ('', [{'field_name': 'name', 'ascending': True}]), ("name LIKE 'm%'", [])])
def test_empty_fields_page_to_completion(store, filter_string, order_by):
    collect(store, filter_string, order_by)


@pytest.mark.parametrize(('filter_string', 'order_by'), [
    (None, None), ("name LIKE 'm%'", [{'field_name': 'name', 'ascending': True}])])
def test_normal_pagination_controls(store, filter_string, order_by):
    collect(store, filter_string, order_by)


@pytest.mark.parametrize('mismatch', ['experiments', 'filter', 'order'])
def test_real_store_rejects_changed_request_fields(store, mismatch):
    value, experiment, _ = store
    order = [{'field_name': 'name', 'ascending': True}]
    page = value.search_logged_models([experiment], filter_string="name LIKE 'm%'", order_by=order, max_results=2)
    assert page.token
    experiments = [experiment] if mismatch != 'experiments' else ['999999']
    filter_string = "name LIKE 'm%'" if mismatch != 'filter' else "name = 'other'"
    requested_order = order if mismatch != 'order' else [{'field_name': 'name', 'ascending': False}]
    with pytest.raises(MlflowException, match='in the page token do not match|in the page token does not match') as error:
        value.search_logged_models(experiments, filter_string=filter_string,
                                   order_by=requested_order, max_results=2, page_token=page.token)
    assert error.value.error_code == 'INVALID_PARAMETER_VALUE'
