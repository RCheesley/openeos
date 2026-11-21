/**
 * Session keep-alive
 * Tells the server that a page which is in use without navigating (the meeting
 * runner, while its timer runs) is still open, so the idle timeout does not
 * sign the user out. Reads data-keepalive-url, data-keepalive-seconds and
 * data-csrf-token from its own script tag. Stops as soon as the server says
 * the page no longer counts, or the session has ended.
 */
(function () {
    'use strict';

    const script = document.currentScript;
    if (!script) return;

    const url = script.dataset.keepaliveUrl;
    const seconds = parseInt(script.dataset.keepaliveSeconds, 10);
    if (!url || !(seconds > 0)) return;

    const timer = setInterval(function () {
        fetch(url, {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'X-CSRFToken': script.dataset.csrfToken, 'Accept': 'application/json' },
        }).then(function (response) {
            if (!response.ok || response.redirected) { clearInterval(timer); return null; }
            return response.json();
        }).then(function (data) {
            if (data && !data.active) clearInterval(timer);
        }).catch(function () { /* offline for a moment: try again next time */ });
    }, seconds * 1000);
})();
