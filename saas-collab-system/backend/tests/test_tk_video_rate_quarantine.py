from decimal import Decimal
import pytest
from apps.influencers.tiktok_video_sync import project, DatasetError


def test_rate_quarantine_preserves_other_metrics_and_source():
    source={'id':'123','total_performance':{'views':15,'video_finish_rate':'2.0000','click_through_rate':'1.5000'}}
    result=project(source,'PHP',quarantine_rates=True)
    assert result['metrics']['finish_rate'] is None
    assert result['metrics']['views']==15
    assert result['metrics']['ctr']==Decimal('1.5000')
    assert result['quarantined_rates']==['video_finish_rate']
    assert source['total_performance']['video_finish_rate']=='2.0000'


@pytest.mark.parametrize('value',['-1','NaN','Infinity','broken'])
def test_other_invalid_numbers_still_reject(value):
    with pytest.raises(DatasetError):
        project({'id':'123','total_performance':{'video_finish_rate':value}},'PHP',quarantine_rates=True)


def test_valid_rate_and_missing_remain_distinct():
    result=project({'id':'123','total_performance':{'video_finish_rate':'0'}},'PHP',quarantine_rates=True)
    assert result['metrics']['finish_rate']==0
    assert result['metrics']['v_to_l_rate'] is None
    assert result['quarantined_rates']==[]
