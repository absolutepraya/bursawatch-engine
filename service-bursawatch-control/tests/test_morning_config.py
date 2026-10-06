from pathlib import Path
from copy import deepcopy
from fastapi.testclient import TestClient
from control_plane.api import create_app
from control_plane.auth import StaticTokenAuth
from control_plane.store import InMemoryStore
from control_plane.validators import validators_from_directories, validators_from_environment

OWNER='bursawatch-dc-morning-brief'
ROOT=Path(__file__).resolve().parents[1]
CONFIG=dict(version=1,timezone='Asia/Jakarta',cutoff_time='07:30',delivery_time='08:00',
    fallback_minutes=5,retry_minutes=15,destination_channel_id=None,instruments=['SPY'],logos={})

def test_authenticated_operator_revisions_and_machine_read_use_existing_config_api():
    validators=validators_from_directories({OWNER:ROOT/'validator-sources'/OWNER})
    store=InMemoryStore();store.seed_config(OWNER,1,deepcopy(CONFIG))
    app=create_app(store=store,auth=StaticTokenAuth(machine_token='fixture-machine',admin_token='fixture-admin'),validators=validators)
    client=TestClient(app);url='/v1/watchers/'+OWNER+'/config'
    assert client.put(url,json={'config_version':1,'config':CONFIG},headers={'Authorization':'Bearer fixture-machine'}).status_code==403
    updated={**CONFIG,'cutoff_time':'06:00','delivery_time':'07:00'}
    saved=client.put(url,json={'config_version':1,'config':updated},headers={'Authorization':'Bearer fixture-admin'})
    assert saved.status_code==200 and saved.json()['revision']==2
    assert client.get(url,headers={'Authorization':'Bearer fixture-machine'}).json()['config']==updated
    bad={**CONFIG,'cutoff_time':'08:00'}
    assert client.put(url,json={'config_version':1,'config':bad},headers={'Authorization':'Bearer fixture-admin'}).status_code==422
    assert client.put(url,json={'config_version':2,'config':CONFIG},headers={'Authorization':'Bearer fixture-admin'}).status_code==422
    assert store.get_config(OWNER).revision==2 and not store.list_jobs(OWNER)

def test_morning_validator_is_bundled_without_host_environment_change(monkeypatch):
    monkeypatch.delenv('CONTROL_PLANE_MORNING_CONFIG_VALIDATOR_DIR',raising=False)
    validators_from_environment()[OWNER](deepcopy(CONFIG))
