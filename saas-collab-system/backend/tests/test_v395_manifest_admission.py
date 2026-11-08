import pytest
from scripts import production_build_only as build


def manifest(source=build.V395_SOURCE_SHA, migration=build.V395_MIGRATION_SHA, **changes):
    args = dict(repository=build.REPOSITORY, release_sha=source,
                backend_digest='sha256:' + 'a' * 64, frontend_digest='sha256:' + 'b' * 64,
                redis_image=build.REDIS_IMAGE, migration_sha=migration)
    args.update(changes)
    return build.make_manifest(**args)


def test_exact_v395_pair():
    result = manifest()
    assert result['git_sha'] == build.V395_SOURCE_SHA
    assert result['migration_sha256'] == build.V395_MIGRATION_SHA


@pytest.mark.parametrize('migration', [build.MIGRATION_SHA, build.V388_MIGRATION_SHA, '0' * 64, ''])
def test_v395_rejects_other_migrations(migration):
    with pytest.raises(ValueError):
        manifest(migration=migration)


@pytest.mark.parametrize('source', [build.V388_SOURCE_SHA, '0' * 40, '580dbe33b857841a78d71b9bc1e810e6b4e9e810'])
def test_v395_migration_not_available_to_other_sources(source):
    with pytest.raises(ValueError):
        manifest(source=source)


@pytest.mark.parametrize('changes', [dict(repository='other/repo'), dict(redis_image='redis:latest'), dict(backend_digest='latest'), dict(frontend_digest='latest')])
def test_existing_identity_guards(changes):
    with pytest.raises(ValueError):
        manifest(**changes)


def test_v388_pair_unchanged():
    assert manifest(build.V388_SOURCE_SHA, build.V388_MIGRATION_SHA)['git_sha'] == build.V388_SOURCE_SHA
