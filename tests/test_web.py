import unittest

from PySide6.QtCore import QStandardPaths, QUrl
from PySide6.QtWebEngineCore import QWebEngineScript
from PySide6.QtWidgets import QApplication

from split_translator.web import (
    AD_DOMAINS,
    CHROME_USER_AGENT,
    AdBlockInterceptor,
    create_web_profile,
)

app = QApplication.instance() or QApplication([])

# Keep the profile's cookies and cache out of the real user data directory.
QStandardPaths.setTestModeEnabled(True)

_SCRIPT_NAME = "split-translator-page-script"


class _FakeRequest:
    """Stands in for a QWebEngineUrlRequestInfo: the interceptor only reads the
    URL and blocks."""

    def __init__(self, url: str):
        self._url = QUrl(url)
        self.blocked = False

    def requestUrl(self) -> QUrl:
        return self._url

    def block(self, value: bool) -> None:
        self.blocked = value


class AdBlockInterceptorTests(unittest.TestCase):
    def _blocked(self, url: str) -> bool:
        request = _FakeRequest(url)
        AdBlockInterceptor().interceptRequest(request)
        return request.blocked

    def test_an_ad_domain_is_blocked(self):
        self.assertTrue(self._blocked("https://pagead2.googlesyndication.com/x.js"))
        self.assertTrue(self._blocked("https://ads.doubleclick.net/ad"))

    def test_the_dictionaries_are_not_blocked(self):
        for url in (
            "https://dictionary.cambridge.org/dictionary/english/dog",
            "https://en.bab.la/dictionary/english-polish/dog",
            "https://www.diki.pl/dog",
            "https://www.google.pl/search?q=dog+meaning",
        ):
            self.assertFalse(self._blocked(url), url)


class PageScriptTests(unittest.TestCase):
    """The injected page script. It must stay out of subframes: injected into a
    subframe whose request the ad interceptor had blocked, it ran in a frame the
    browser had torn down, which made Chromium kill the renderer for a bad IPC
    message, and the app then crashed inside the next load. Blocking ads and
    injecting into every frame are safe apart, fatal together."""

    def _script(self) -> QWebEngineScript:
        profile = create_web_profile()
        self.addCleanup(profile.deleteLater)
        found = profile.scripts().find(_SCRIPT_NAME)
        self.assertEqual(len(found), 1)
        return found[0]

    def test_the_page_script_never_runs_on_subframes(self):
        self.assertFalse(self._script().runsOnSubFrames())

    def test_the_page_script_runs_in_the_page_world_once_it_is_ready(self):
        script = self._script()
        self.assertEqual(
            script.injectionPoint(),
            QWebEngineScript.InjectionPoint.DocumentReady,
        )
        self.assertEqual(
            script.worldId(), QWebEngineScript.ScriptWorldId.MainWorld
        )

    def test_the_profile_presents_a_plain_chrome_agent_and_persists(self):
        profile = create_web_profile()
        self.addCleanup(profile.deleteLater)
        self.assertEqual(profile.httpUserAgent(), CHROME_USER_AGENT)
        self.assertTrue(profile.persistentStoragePath())
        self.assertIn("doubleclick.net", AD_DOMAINS)


if __name__ == "__main__":
    unittest.main()
