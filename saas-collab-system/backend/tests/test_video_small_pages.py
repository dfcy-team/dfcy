import pytest

from apps.influencers.tiktok_shop_dataset import DatasetError
from apps.influencers.tiktok_video_sync import video_page_limit


@pytest.mark.parametrize('size, expected', [(10, 500), (50, 100), (1, 5000), (30, 167)])
def test_small_pages_preserve_bounded_row_capacity(size, expected):
    assert video_page_limit(size) == expected


@pytest.mark.parametrize('size', [0, 51, True, '10', None])
def test_invalid_page_size_is_rejected(size):
    with pytest.raises(DatasetError, match='video_page_size_invalid'):
        video_page_limit(size)
