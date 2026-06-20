"""Web engine setup: a persistent profile, network ad-blocking and on-load JS injection.

This replaces the old approach of hardcoding a User-Agent and removing ads purely with
post-load JavaScript. Instead it uses Qt's built-in mechanisms:

* A *persistent* QWebEngineProfile keeps cookies, cache and Cloudflare clearance on disk,
  so cookie banners and bot checks do not reappear every launch.
* A QWebEngineUrlRequestInterceptor blocks known ad/tracker domains at the network layer,
  before they render (more robust than removing nodes after the fact).
* QWebEngineScript injects cosmetic ad removal and cookie-consent auto-dismiss on every page.
"""

from pathlib import Path

from PySide6.QtCore import QStandardPaths, QUrl
from PySide6.QtWebEngineCore import (
    QWebEngineProfile,
    QWebEngineScript,
    QWebEngineSettings,
    QWebEngineUrlRequestInfo,
    QWebEngineUrlRequestInterceptor,
)

from . import APP_NAME

# A current, plain Chrome User-Agent. Qt's default advertises a "QtWebEngine" token that
# some sites sniff and treat differently; presenting as a normal Chrome build avoids that
# without needing to chase version bumps by hand (the major version rarely matters).
CHROME_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)

# Network-level block list. Substrings matched against the request URL. Blocking here
# stops ad/tracker resources before they load, so there is no render flash.
AD_DOMAINS = (
    "doubleclick.net",
    "googlesyndication.com",
    "googleadservices.com",
    "google-analytics.com",
    "googletagmanager.com",
    "googletagservices.com",
    "adservice.google.com",
    "adnxs.com",
    "amazon-adsystem.com",
    "pubmatic.com",
    "rubiconproject.com",
    "criteo.com",
    "casalemedia.com",
    "scorecardresearch.com",
    "moatads.com",
    "adsafeprotected.com",
)

# Cosmetic ad selectors. Kept from the original app as a fallback for in-page ad slots
# that are served from first-party paths the network filter cannot catch.
BLOCKED_SELECTORS = (
    "iframe[src*='ads']",
    "div[id^='google_ads']",
    "div[id*='ad_leftslot']",
    "div[id*='ad_rightslot']",
    "div[id*='ad_topslot']",
)

# Best-effort cookie-consent dismissal. The persistent profile remembers the choice after
# the first accept, so this mainly smooths the very first launch.
_CONSENT_BUTTON_TEXTS = (
    "accept all",
    "i agree",
    "agree",
    "accept cookies",
    "accept",
    "zaakceptuj wszystko",
    "zaakceptuj",
    "zgadzam się",
    "akceptuję",
)


def _selectors_js() -> str:
    return ", ".join(f'"{s}"' for s in BLOCKED_SELECTORS)


# Runs at document end on every page: removes cosmetic ads (with a MutationObserver for
# dynamically inserted ones) and tries to click a cookie-consent button.
_PAGE_SCRIPT = f"""
(function() {{
    const selectors = [{_selectors_js()}];
    const consentTexts = {list(_CONSENT_BUTTON_TEXTS)};

    function removeAds() {{
        selectors.forEach(selector => {{
            document.querySelectorAll(selector).forEach(el => el.remove());
        }});
    }}

    function dismissConsent() {{
        // Only real buttons dismiss a consent banner. Anchors that navigate to
        // another page (href to a path/URL) are dictionary content, not consent
        // controls; clicking them would hijack the view. So skip linking anchors.
        const clickable = document.querySelectorAll('button, [role="button"], input[type="submit"]');
        for (const el of clickable) {{
            const label = (el.innerText || el.textContent || el.value || '').trim().toLowerCase();
            if (!label) continue;
            // Exact match only. A substring match on bare words like "agree" or
            // "accept" clicks in-content links (e.g. on the "resentment" entry).
            if (consentTexts.includes(label)) {{
                el.click();
                return true;
            }}
        }}
        return false;
    }}

    function run() {{
        removeAds();
        dismissConsent();
    }}

    run();

    // Re-run for content injected after initial load (consent banners, lazy ads).
    const observer = new MutationObserver(run);
    if (document.body) {{
        observer.observe(document.body, {{ childList: true, subtree: true }});
    }}

    // Stop observing once the page has settled to avoid running forever.
    setTimeout(() => observer.disconnect(), 8000);
}})();
"""


class AdBlockInterceptor(QWebEngineUrlRequestInterceptor):
    """Blocks requests to known ad/tracker domains at the network layer."""

    def interceptRequest(self, info: QWebEngineUrlRequestInfo) -> None:
        url = info.requestUrl().host()
        if any(domain in url for domain in AD_DOMAINS):
            info.block(True)


def _profile_storage_dir() -> Path:
    """Return the on-disk directory for the persistent web profile.

    Uses the OS app-data location (e.g. ~/.local/share/split-translator on Linux).
    """
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation
    )
    storage = Path(base) / "web-profile"
    storage.mkdir(parents=True, exist_ok=True)
    return storage


def create_web_profile(parent=None) -> QWebEngineProfile:
    """Create and configure the persistent web profile shared by all views.

    The returned profile owns the interceptor and injected script, persists cookies and
    cache to disk, and presents a plain Chrome User-Agent.
    """
    storage = _profile_storage_dir()

    # A named profile is persistent (an off-the-record profile would not be).
    profile = QWebEngineProfile(APP_NAME, parent)
    profile.setPersistentStoragePath(str(storage))
    profile.setCachePath(str(storage / "cache"))
    profile.setPersistentCookiesPolicy(
        QWebEngineProfile.PersistentCookiesPolicy.AllowPersistentCookies
    )
    profile.setHttpUserAgent(CHROME_USER_AGENT)

    settings = profile.settings()
    settings.setAttribute(
        QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False
    )
    settings.setAttribute(
        QWebEngineSettings.WebAttribute.LocalStorageEnabled, True
    )

    # Network-level ad blocking. The interceptor is parented to the profile so it lives
    # as long as the profile does.
    interceptor = AdBlockInterceptor(profile)
    profile.setUrlRequestInterceptor(interceptor)

    # Cosmetic ad removal + consent dismissal injected into every page.
    script = QWebEngineScript()
    script.setName("split-translator-page-script")
    script.setSourceCode(_PAGE_SCRIPT)
    script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentReady)
    script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
    script.setRunsOnSubFrames(True)
    profile.scripts().insert(script)

    return profile
