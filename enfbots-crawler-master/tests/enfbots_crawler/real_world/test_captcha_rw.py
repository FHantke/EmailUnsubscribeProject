import pytest

from enfbots_crawler.main import run_domain

testing_recaptcha_v2 = [
    "singh.com.au",
    "psoriasis-association.org.uk",
    "www2.gogoanime.video",
    "store.steampowered.com",
    "control.stackpath.com",
    "android-mediaplayer.de",
    "iwara.tv",
    "musicbrainz.org",
    "livejournal.com",
    "appgyver.com",
    "tarinatarantino.com",
]
testing_recaptcha_v3 = ["www.instantprint.co.uk"]


testing_img_captcha = [
    "user.17track.net",
    "dzlm.de",
    "7fonts.net",
    "en.wikibooks.org",
    "1337x.to",
    "www.minds.com",
    "www.herz-jesu-plauen.de",
]


@pytest.mark.parametrize("hostname", testing_img_captcha)
def test_img_captcha(hostname, db_memory):
    assert run_domain(hostname)


@pytest.mark.parametrize("hostname", testing_recaptcha_v2)
def test_recaptchav2(hostname, db_memory):
    assert run_domain(hostname)


@pytest.mark.parametrize("hostname", testing_recaptcha_v3)
def test_rcaptchav3(hostname, db_memory):
    assert run_domain(hostname)
