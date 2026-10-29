import pytest
from scripts.production_build_only import (
    V330_CLOUD_SHA, V330_CLOUD_TREE, V330_SOURCE_MIGRATION_SHA,
    validate_v330_source, make_manifest, REDIS_IMAGE,
)

def test_exact_cloud_identity():
    assert validate_v330_source(V330_CLOUD_SHA, V330_CLOUD_TREE, V330_SOURCE_MIGRATION_SHA)
    assert make_manifest('dfcy-team/dfcy', V330_CLOUD_SHA, 'sha256:'+'a'*64,
                         'sha256:'+'b'*64, REDIS_IMAGE, V330_SOURCE_MIGRATION_SHA)['git_sha']==V330_CLOUD_SHA

@pytest.mark.parametrize('index', [0,1,2])
def test_reject_unapproved_cloud_identity(index):
    args=[V330_CLOUD_SHA,V330_CLOUD_TREE,V330_SOURCE_MIGRATION_SHA]
    args[index]='0'*len(args[index])
    with pytest.raises(ValueError):validate_v330_source(*args)
