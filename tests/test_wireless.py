from unittest.mock import mock_open, patch

from wifi_observer import read_wifi_signal


SAMPLE = """Inter-| sta-| Quality        | Discarded packets               | Missed | WE
 face | tus | link level noise |  nwid  crypt   frag  retry   misc | beacon | 22
wlan0: 0000   70.  -40.  -256
"""


@patch("builtins.open", new_callable=mock_open, read_data=SAMPLE)
def test_parse_wireless(mock_file):
    level, quality = read_wifi_signal("wlan0")

    assert level == -40.0
    assert quality == 100.0


@patch("builtins.open", new_callable=mock_open, read_data=SAMPLE)
def test_unknown_interface(mock_file):
    level, quality = read_wifi_signal("eth0")

    assert level is None
    assert quality is None
