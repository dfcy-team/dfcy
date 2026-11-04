from datetime import date
import pytest
from rest_framework.exceptions import ValidationError
from apps.integrations.gmv_max_relationship import verify_pair, STORE_PATH, EXCLUSIVE_PATH, attach_relationship_coverage


def get_response(primary='1', authorization='EFFECTIVE', response_advertiser='1', response_store='9', bc='8'):
    def get(path, params):
        if path == STORE_PATH:
            return {'store_list': [{'store_id': '9', 'store_authorized_bc_id': bc,
                'is_gmv_max_available': True, 'exclusive_authorized_advertiser_info': {'advertiser_id': primary}}]}
        assert path == EXCLUSIVE_PATH
        assert params == {'advertiser_id': '1', 'store_id': '9', 'store_authorized_bc_id': '8'}
        return {'advertiser_id': response_advertiser, 'store_id': response_store, 'authorization_status': authorization}
    return get


def test_exact_platform_ids_confirm_current_and_noncurrent_without_timezone():
    assert verify_pair(get_response(), '1', '9')['relationship_status'] == 'current_verified'
    assert verify_pair(get_response(primary='2', authorization='UNAUTHORIZED'), '1', '9')['relationship_status'] == 'not_current'


@pytest.mark.parametrize('changes', [{'response_store': 'other'}, {'response_advertiser': '2'},
    {'primary': '2'}, {'authorization': 'UNKNOWN'}, {'bc': None}])
def test_ambiguous_missing_or_conflicting_identity_fails_closed(changes):
    with pytest.raises(ValidationError):
        verify_pair(get_response(**changes), '1', '9')


def row(advertiser, day, **changes):
    return dict(store_code='S', advertiser_id=advertiser, platform_store_id='9',
                currency='USD', timezone='UTC', date=f'2026-11-0{day}', relationship_verified=True, **changes)


def coverage(rows, observations=None):
    subjects = [dict(mapping_id=i, store_id=3, store_code='S', advertiser_id=str(i),
                     currency='USD', mapping_timezone='UTC') for i in [1, 2]]
    group = dict(store_code='S', platform_store_id='9', currency='USD', timezone='UTC', cost='999', conflict=False)
    result = attach_relationship_coverage([group], rows, subjects, observations or [], date(2026, 11, 1), date(2026, 11, 7))[0]
    assert result['cost'] == '999'
    return result['api_coverage']


def test_historical_switch_keeps_both_owners_at_their_actual_report_dates():
    data = [row('1', d) for d in range(1, 4)] + [row('2', d) for d in range(4, 8)]
    result = coverage(data)
    assert result['account_count'] == 2 and result['expected_days'] == 7
    assert result['stored_days'] == 7 and result['complete']


def test_current_authorization_cannot_overwrite_previous_week_owner():
    data = [row('1', d) for d in range(1, 8)]
    current = dict(mapping_id=2, platform_store_id='9', relationship_status='current_verified',
                   observed_at='2026-11-08T00:00:00+00:00', fresh=True)
    result = coverage(data, [current])
    assert result['account_count'] == 1 and result['complete']


def test_real_missing_day_and_legacy_unknown_are_not_complete_or_zero():
    result = coverage([row('1', d) for d in range(1, 7)])
    assert result['stored_days'] == 6 and result['expected_days'] == 7 and not result['complete']
    unknown = row('1', 7)
    unknown['relationship_verified'] = False
    result = coverage([unknown])
    assert not result['complete'] and result['unverified_report_days'] == 1


def test_same_timezone_other_store_never_joins_coverage():
    data = [row('1', d) for d in range(1, 8)]
    unrelated = row('2', 1)
    unrelated['platform_store_id'] = 'different'
    result = coverage(data + [unrelated])
    assert result['account_count'] == 1 and result['expected_days'] == 7


def test_new_current_relation_is_not_backdated_and_missing_report_stays_unknown():
    observation = dict(mapping_id=2, platform_store_id='9', relationship_status='current_verified',
                       observed_at='2026-11-07T10:00:00+00:00', fresh=True)
    subjects = [dict(mapping_id=2, store_code='S', advertiser_id='2', currency='USD', mapping_timezone='UTC')]
    result = attach_relationship_coverage([], [], subjects, [observation], date(2026, 11, 1), date(2026, 11, 7))[0]
    assert result['cost'] is None and not result['api_coverage']['complete']
    assert result['api_coverage']['expected_days'] == 1 and result['api_coverage']['stored_days'] == 0


def test_observation_from_other_currency_or_timezone_cannot_change_group_coverage():
    for currency, zone in [('EUR', 'UTC'), ('USD', 'Asia/Bangkok')]:
        group = dict(store_code='S', platform_store_id='9', currency='USD', timezone='UTC', conflict=False)
        subjects = [
            dict(mapping_id=1, store_code='S', advertiser_id='1', currency='USD', mapping_timezone='UTC'),
            dict(mapping_id=2, store_code='S', advertiser_id='1', currency=currency, mapping_timezone=zone),
        ]
        observation = dict(mapping_id=2, platform_store_id='9', relationship_status='current_verified',
                           observed_at='2026-11-07T10:00:00+00:00', fresh=True)
        data = [row('1', d) for d in range(1, 8)]
        baseline = attach_relationship_coverage([group], data, subjects, [], date(2026, 11, 1), date(2026, 11, 7))[0]
        actual = attach_relationship_coverage([group], data, subjects, [observation], date(2026, 11, 1), date(2026, 11, 7))[0]
        assert actual['api_coverage'] == baseline['api_coverage']
