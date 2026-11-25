import json,os
from unittest.mock import Mock
import pytest
from cryptography.fernet import Fernet
from apps.integrations.custody_service import EncryptedFileCredentialStore
from apps.integrations.file_custody import FileCustodyError,_operation_hash

@pytest.fixture
def operation_store(tmp_path):
    key=tmp_path/'key';key.write_bytes(Fernet.generate_key());key.chmod(0o400)
    store=EncryptedFileCredentialStore(tmp_path/'records',key)
    for i in range(120):
        store._write(f'cred_{i:04d}',{'credential_id':f'cred_{i:04d}','token_id':f'tok_{i:04d}',
            'version':1,'status':'active','operation_id_hash':_operation_hash(f'synthetic-operation-{i}'),
            'credentials':{'access_token':'SYNTHETIC_ACCESS'}})
    return store

def test_operation_lookup_authenticates_only_matching_payload(operation_store,monkeypatch):
    store=operation_store;decrypt=Mock(wraps=store._decrypt_values);monkeypatch.setattr(store,'_decrypt_values',decrypt)
    assert store.lookup_operation('synthetic-absent-operation')=={'found':False}
    assert decrypt.call_count==0
    result=store.lookup_operation('synthetic-operation-119')
    assert result['found'] and result['credential_id']=='cred_0119'
    assert decrypt.call_count==1
    assert 'SYNTHETIC_ACCESS' not in json.dumps(result)

def test_operation_lookup_rejects_tampered_selected_ciphertext(operation_store):
    store=operation_store;path=store.path/'cred_0119.json';record=json.loads(path.read_text())
    record['credentials_encrypted']['ciphertext']='SYNTHETIC_INVALID_CIPHERTEXT';path.write_text(json.dumps(record))
    with pytest.raises(FileCustodyError):store.lookup_operation('synthetic-operation-119')

def test_operation_lookup_rejects_conflicting_references(operation_store):
    store=operation_store
    store._write('cred_duplicate',{'credential_id':'cred_duplicate','token_id':'tok_duplicate','version':1,
        'status':'active','operation_id_hash':_operation_hash('synthetic-operation-119'),
        'credentials':{'access_token':'SYNTHETIC_OTHER'}})
    with pytest.raises(FileCustodyError,match='conflicting'):store.lookup_operation('synthetic-operation-119')

@pytest.mark.skipif(os.name=='nt',reason='POSIX custody file permissions')
def test_operation_lookup_rejects_unsafe_selected_file(operation_store):
    store=operation_store;(store.path/'cred_0119.json').chmod(0o644)
    with pytest.raises(FileCustodyError):store.lookup_operation('synthetic-operation-119')
