// ==UserScript==
// @name         SAM.gov Download All ZIP Capture
// @namespace    https://github.com/DeerSpotter/samgovsearch
// @version      0.2.0
// @description  Captures SAM.gov Download All Attachments/Links ZIP URLs and can immediately download them before the short S3 expiry window closes.
// @author       DeerSpotter
// @match        https://sam.gov/opp/*/view*
// @match        https://sam.gov/opp/*
// @run-at       document-start
// @grant        GM_setClipboard
// @grant        GM_download
// @grant        GM_notification
// @connect      iae-fbo-attachments.s3.amazonaws.com
// ==/UserScript==

(function () {
    'use strict';

    const SCRIPT_PREFIX = '[SAM ZIP Capture]';
    const ZIP_URL_PATTERN = /https?:\/\/[^\s"'<>]+(?:\.zip\?|\.zip$|X-Amz-Algorithm=AWS4-HMAC-SHA256)[^\s"'<>]*/ig;
    const S3_ZIP_PATTERN = /https?:\/\/iae-fbo-attachments\.s3\.amazonaws\.com\/[^\s"'<>]+/ig;

    const state = {
        captures: [],
        seen: new Set(),
        downloaded: new Set(),
        panelReady: false,
        latestUrl: '',
        latestSource: '',
        clickCount: 0,
        instantPending: false,
        instantStartedAt: 0,
        lastDownloadStatus: '',
    };

    function log(...args) {
        console.log(SCRIPT_PREFIX, ...args);
    }

    function cleanUrl(rawUrl) {
        if (!rawUrl) return '';
        let value = String(rawUrl).trim();
        value = value.replace(/&amp;/g, '&');
        value = value.replace(/[)\].,;]+$/g, '');
        return value;
    }

    function isCandidateZipUrl(url) {
        if (!url) return false;
        const value = cleanUrl(url);
        return /\.zip(?:\?|$)/i.test(value) || /X-Amz-Algorithm=AWS4-HMAC-SHA256/i.test(value);
    }

    function captureUrl(rawUrl, source) {
        const url = cleanUrl(rawUrl);
        if (!isCandidateZipUrl(url)) return;

        const now = Date.now();
        const alreadySeen = state.seen.has(url);
        if (!alreadySeen) {
            state.seen.add(url);
            state.latestUrl = url;
            state.latestSource = source || 'unknown';
            state.captures.unshift({
                url,
                source: state.latestSource,
                capturedAt: new Date(now).toISOString(),
                capturedAtMs: now,
                expiresInSeconds: parseSignedUrlExpiry(url),
            });

            log('Captured ZIP URL from', state.latestSource, url);
            notify('SAM.gov ZIP URL captured', 'Use Instant Download, not copy/paste. These URLs can expire in about 9 seconds.');
        }

        if (state.instantPending && now >= state.instantStartedAt - 250) {
            instantDownloadUrl(url, `instant capture from ${source || 'unknown'}`);
            state.instantPending = false;
        }

        updatePanel();
    }

    function parseSignedUrlExpiry(url) {
        try {
            const parsed = new URL(url);
            const expires = parsed.searchParams.get('X-Amz-Expires');
            if (expires && /^\d+$/.test(expires)) return Number(expires);
        } catch (_err) {
            // Ignore parse errors.
        }
        return null;
    }

    function notify(title, text) {
        try {
            GM_notification({ title, text, timeout: 3500 });
        } catch (_err) {
            // Notification support varies by userscript manager.
        }
    }

    function scanText(text, source) {
        if (!text) return;
        const value = String(text);
        let match;

        ZIP_URL_PATTERN.lastIndex = 0;
        while ((match = ZIP_URL_PATTERN.exec(value)) !== null) {
            captureUrl(match[0], source);
        }

        S3_ZIP_PATTERN.lastIndex = 0;
        while ((match = S3_ZIP_PATTERN.exec(value)) !== null) {
            captureUrl(match[0], source);
        }
    }

    function scanNode(node, source) {
        if (!node || node.nodeType !== 1) return;

        if (node.matches && node.matches('a[href]')) {
            captureUrl(node.href || node.getAttribute('href'), source + ' anchor');
        }

        if (node.querySelectorAll) {
            node.querySelectorAll('a[href]').forEach((anchor) => {
                captureUrl(anchor.href || anchor.getAttribute('href'), source + ' anchor');
            });
        }

        const text = node.textContent || '';
        if (text.includes('iae-fbo-attachments') || text.includes('X-Amz-Algorithm') || text.includes('.zip')) {
            scanText(text.slice(0, 200000), source + ' text');
        }
    }

    function patchFetch() {
        if (!window.fetch || window.fetch.__samZipCapturePatched) return;
        const originalFetch = window.fetch;
        window.fetch = async function (...args) {
            const requestUrl = args && args[0] && (args[0].url || args[0]);
            captureUrl(requestUrl, 'fetch request');

            const response = await originalFetch.apply(this, args);
            try {
                captureUrl(response.url, 'fetch response URL');
                const contentType = response.headers && response.headers.get && response.headers.get('content-type');
                if (!contentType || /json|text|html|javascript/i.test(contentType)) {
                    response.clone().text().then((body) => scanText(body, 'fetch response body')).catch(() => {});
                }
            } catch (err) {
                log('fetch capture warning:', err);
            }
            return response;
        };
        window.fetch.__samZipCapturePatched = true;
        log('fetch patched');
    }

    function patchXHR() {
        if (!window.XMLHttpRequest || window.XMLHttpRequest.prototype.__samZipCapturePatched) return;

        const originalOpen = window.XMLHttpRequest.prototype.open;
        const originalSend = window.XMLHttpRequest.prototype.send;

        window.XMLHttpRequest.prototype.open = function (method, url, ...rest) {
            this.__samZipCaptureUrl = url;
            captureUrl(url, 'xhr open');
            return originalOpen.call(this, method, url, ...rest);
        };

        window.XMLHttpRequest.prototype.send = function (...args) {
            this.addEventListener('load', function () {
                try {
                    captureUrl(this.responseURL, 'xhr response URL');
                    const type = this.getResponseHeader && this.getResponseHeader('content-type');
                    if ((!type || /json|text|html|javascript/i.test(type)) && typeof this.responseText === 'string') {
                        scanText(this.responseText, 'xhr response body');
                    }
                } catch (err) {
                    log('xhr capture warning:', err);
                }
            });
            return originalSend.apply(this, args);
        };

        window.XMLHttpRequest.prototype.__samZipCapturePatched = true;
        log('XMLHttpRequest patched');
    }

    function findDownloadAllButton() {
        const candidates = Array.from(document.querySelectorAll('a, button, [role="button"]'));
        return candidates.find((element) => {
            const text = (element.textContent || '').replace(/\s+/g, ' ').trim().toLowerCase();
            return text.includes('download all attachments') || text.includes('download all attachments/links');
        });
    }

    function clickDownloadAll() {
        const button = findDownloadAllButton();
        if (!button) {
            log('Download All Attachments/Links button not found on this page yet.');
            alert('Download All Attachments/Links button was not found yet. Scroll to Attachments/Links or wait for the page to finish loading, then try again.');
            return false;
        }
        state.clickCount += 1;
        log('Clicking Download All Attachments/Links button', button);
        button.click();
        updatePanel();
        return true;
    }

    function instantClickDownloadAll() {
        state.instantPending = true;
        state.instantStartedAt = Date.now();
        state.lastDownloadStatus = 'Armed. Waiting for SAM.gov to generate the ZIP URL...';
        log('Instant mode armed. The first generated ZIP URL will be downloaded immediately.');
        const clicked = clickDownloadAll();
        if (!clicked) {
            state.instantPending = false;
            state.lastDownloadStatus = 'Could not arm instant download because the Download All button was not found.';
        }
        updatePanel();
    }

    function copyLatest() {
        if (!state.latestUrl) {
            alert('No ZIP URL captured yet. Click Download All or use the page button first.');
            return;
        }
        GM_setClipboard(state.latestUrl, 'text');
        log('Copied latest ZIP URL to clipboard. It may expire in seconds:', state.latestUrl);
        state.lastDownloadStatus = 'Copied latest URL. Warning: copied S3 URLs usually expire in about 9 seconds.';
        updatePanel();
    }

    function downloadLatest() {
        if (!state.latestUrl) {
            alert('No ZIP URL captured yet. Click Download All or use the page button first.');
            return;
        }
        instantDownloadUrl(state.latestUrl, 'manual latest download');
    }

    function instantDownloadUrl(url, reason) {
        const clean = cleanUrl(url);
        if (!clean || state.downloaded.has(clean)) return;
        state.downloaded.add(clean);

        const name = makeZipName();
        state.lastDownloadStatus = `Downloading immediately: ${name}`;
        log('Instant ZIP download starting:', reason, clean);
        updatePanel();

        try {
            GM_download({
                url: clean,
                name,
                saveAs: false,
                onload: () => {
                    state.lastDownloadStatus = `Downloaded: ${name}`;
                    log('Instant ZIP download completed:', name);
                    notify('SAM.gov ZIP downloaded', name);
                    updatePanel();
                },
                onerror: (err) => {
                    state.lastDownloadStatus = 'GM_download failed. Opening URL directly as immediate fallback.';
                    log('GM_download failed, opening URL directly:', err);
                    window.location.href = clean;
                    updatePanel();
                },
                ontimeout: () => {
                    state.lastDownloadStatus = 'GM_download timed out. The URL probably expired.';
                    log('GM_download timed out. URL probably expired.');
                    updatePanel();
                },
            });
        } catch (err) {
            state.lastDownloadStatus = 'GM_download unavailable. Opening URL directly as immediate fallback.';
            log('GM_download unavailable, opening URL directly:', err);
            window.location.href = clean;
            updatePanel();
        }
    }

    function makeZipName() {
        const title = document.title || 'samgov_attachments';
        const safe = title.replace(/\s*\|\s*SAM\.gov.*$/i, '').replace(/[^a-z0-9._ -]+/ig, '_').trim();
        const stamped = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
        return `${safe || 'samgov_attachments'}_${stamped}.zip`;
    }

    function clearCaptures() {
        state.captures = [];
        state.seen.clear();
        state.downloaded.clear();
        state.latestUrl = '';
        state.latestSource = '';
        state.instantPending = false;
        state.instantStartedAt = 0;
        state.lastDownloadStatus = '';
        updatePanel();
    }

    function buildPanel() {
        if (document.getElementById('sam-zip-capture-panel')) return;

        const panel = document.createElement('div');
        panel.id = 'sam-zip-capture-panel';
        panel.style.cssText = [
            'position:fixed',
            'right:12px',
            'bottom:12px',
            'z-index:2147483647',
            'width:410px',
            'max-width:calc(100vw - 24px)',
            'font-family:Arial,sans-serif',
            'font-size:12px',
            'background:#111827',
            'color:#f9fafb',
            'border:1px solid #374151',
            'border-radius:8px',
            'box-shadow:0 8px 24px rgba(0,0,0,.35)',
            'padding:10px',
        ].join(';');

        panel.innerHTML = `
            <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:6px;">
                <strong>SAM ZIP Capture</strong>
                <button id="samzip-hide" style="font-size:11px;">Hide</button>
            </div>
            <div id="samzip-status" style="line-height:1.35;margin-bottom:8px;color:#d1d5db;">Waiting for ZIP URL...</div>
            <div id="samzip-download-status" style="line-height:1.35;margin-bottom:8px;color:#fde68a;"></div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:8px;">
                <button id="samzip-instant">Instant Download All ZIP</button>
                <button id="samzip-click">Click Only</button>
                <button id="samzip-download">Fast Download Latest</button>
                <button id="samzip-copy">Copy Latest URL</button>
                <button id="samzip-clear">Clear</button>
            </div>
            <div style="line-height:1.35;margin-bottom:6px;color:#fca5a5;">Copied links usually expire almost immediately. Use Instant Download for real testing.</div>
            <textarea id="samzip-latest" readonly style="box-sizing:border-box;width:100%;height:82px;font-size:11px;resize:vertical;"></textarea>
            <div id="samzip-list" style="margin-top:8px;max-height:120px;overflow:auto;border-top:1px solid #374151;padding-top:6px;"></div>
        `;

        document.documentElement.appendChild(panel);
        panel.querySelector('#samzip-instant').addEventListener('click', instantClickDownloadAll);
        panel.querySelector('#samzip-click').addEventListener('click', clickDownloadAll);
        panel.querySelector('#samzip-copy').addEventListener('click', copyLatest);
        panel.querySelector('#samzip-download').addEventListener('click', downloadLatest);
        panel.querySelector('#samzip-clear').addEventListener('click', clearCaptures);
        panel.querySelector('#samzip-hide').addEventListener('click', () => {
            panel.style.display = 'none';
            const restore = document.createElement('button');
            restore.id = 'sam-zip-capture-restore';
            restore.textContent = 'SAM ZIP';
            restore.style.cssText = 'position:fixed;right:12px;bottom:12px;z-index:2147483647;font-size:12px;';
            restore.addEventListener('click', () => {
                panel.style.display = 'block';
                restore.remove();
            });
            document.documentElement.appendChild(restore);
        });

        state.panelReady = true;
        updatePanel();
    }

    function updatePanel() {
        if (!state.panelReady) return;
        const status = document.getElementById('samzip-status');
        const downloadStatus = document.getElementById('samzip-download-status');
        const latest = document.getElementById('samzip-latest');
        const list = document.getElementById('samzip-list');
        if (!status || !downloadStatus || !latest || !list) return;

        if (state.latestUrl) {
            const latestCapture = state.captures[0] || {};
            const expiryText = latestCapture.expiresInSeconds ? ` Signed URL expiry: <b>${latestCapture.expiresInSeconds}s</b>.` : '';
            status.innerHTML = `Captured <b>${state.captures.length}</b> ZIP URL(s). Latest source: <b>${escapeHtml(state.latestSource)}</b>. Clicked Download All: <b>${state.clickCount}</b>.${expiryText}`;
            latest.value = state.latestUrl;
        } else if (state.instantPending) {
            status.innerHTML = `Instant mode is armed. Waiting for SAM.gov to inject the ZIP URL. Clicked: <b>${state.clickCount}</b>.`;
            latest.value = '';
        } else {
            status.innerHTML = `Waiting for ZIP URL. Use <b>Instant Download All ZIP</b> for the 9-second URL window. Clicked: <b>${state.clickCount}</b>.`;
            latest.value = '';
        }

        downloadStatus.textContent = state.lastDownloadStatus || '';

        list.innerHTML = state.captures.slice(0, 10).map((item, index) => {
            const expiry = item.expiresInSeconds ? ` expires=${item.expiresInSeconds}s` : '';
            return `<div style="margin-bottom:6px;word-break:break-all;"><b>#${index + 1}</b> ${escapeHtml(item.source)}${expiry}<br><a href="${escapeAttr(item.url)}" target="_blank" style="color:#93c5fd;">${escapeHtml(item.url)}</a></div>`;
        }).join('');
    }

    function escapeHtml(value) {
        return String(value).replace(/[&<>"]/g, (char) => ({
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
        }[char]));
    }

    function escapeAttr(value) {
        return escapeHtml(value).replace(/'/g, '&#39;');
    }

    function startDomObserver() {
        const observer = new MutationObserver((mutations) => {
            for (const mutation of mutations) {
                if (mutation.type === 'attributes') {
                    scanNode(mutation.target, 'mutation attribute');
                }
                for (const node of mutation.addedNodes || []) {
                    scanNode(node, 'mutation added');
                }
            }
        });
        observer.observe(document.documentElement, {
            subtree: true,
            childList: true,
            attributes: true,
            attributeFilter: ['href', 'src'],
        });
        log('DOM observer active');
    }

    function initialScanLoop() {
        let count = 0;
        const timer = setInterval(() => {
            count += 1;
            if (document.body) {
                scanNode(document.body, 'periodic body scan');
            }
            if (count >= 60 || state.latestUrl) {
                clearInterval(timer);
            }
        }, 1000);
    }

    patchFetch();
    patchXHR();

    document.addEventListener('DOMContentLoaded', () => {
        buildPanel();
        startDomObserver();
        scanNode(document.body, 'DOMContentLoaded');
        initialScanLoop();
    });

    if (document.readyState !== 'loading') {
        setTimeout(() => {
            buildPanel();
            startDomObserver();
            if (document.body) scanNode(document.body, 'late init');
            initialScanLoop();
        }, 0);
    }
})();
