from typing import TYPE_CHECKING

from ufor.selector import LibraryConfig

if TYPE_CHECKING:
    from reccy.pytest_plugin import SampleConfigRegression

pytest_plugins = ['reccy.pytest_plugin']


def test_sample_config(sample_config_regression: 'SampleConfigRegression') -> None:
    sample_config_regression(LibraryConfig)
