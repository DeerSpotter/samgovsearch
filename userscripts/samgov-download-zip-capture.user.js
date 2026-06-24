// ==UserScript==
// @name         SAM.gov Download All ZIP Capture
// @namespace    https://github.com/DeerSpotter/samgovsearch
// @version      0.1.0
// @description  Captures the short-lived SAM.gov Download All Attachments/Links ZIP URL so the Python app can mirror the working browser behavior.
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
        panelReady: false,
        latestUrl: '',
        latestSource: '',
        clickCount: 0,
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
        if (state.seen.has(url)) return;

        state.seen.add(url);
        state.latestUrl = url;
        state.latestSource = source || 'unknown';
        state.captures.unshift({
            url,
            source: state.latestSource,
            capturedAt: new Date().toISOString(),
        });

        log('Captured ZIP URL from', state.latestSource, url);
        updatePanel();

        try {
            GM_notification({
                title: 'SAM.gov ZIP URL captured',
                text: 'Click the Tampermonkey panel to copy or download it.',
                timeout: 5000,
            });
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

        // The SAM.gov page injects a visible "Download Link / click here" anchor after clicking
        // Download All Attachments/Links. Scan a bounded amount of text so the observer stays light.
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
            return;
        }
        state.clickCount += 1;
        log('Clicking Download All Attachments/Links button', button);
        button.click();
        updatePanel();
    }

    function copyLatest() {
        if (!state.latestUrl) {
            alert('No ZIP URL captured yet. Click Download All or use the page button first.');
            return;
        }
        GM_setClipboard(state.latestUrl, 'text');
        log('Copied latest ZIP URL to clipboard');
    }

    function downloadLatest() {
        if (!state.latestUrl) {
            alert('No ZIP URL captured yet. Click Download All or use the page button first.');
            return;
        }
        const name = makeZipName();
        try {
            GM_download({
                url: state.latestUrl,
                name,
                saveAs: true,
                onerror: (err) => {
                    log('GM_download failed, opening URL directly:', err);
                    window.open(state.latestUrl, '_blank', 'noopener,noreferrer');
                },
            });
        } catch (err) {
            log('GM_download unavailable, opening URL directly:', err);
            window.open(state.latestUrl, '_blank', 'noopener,noreferrer');
        }
    }

    function makeZipName() {
        const title = document.title || 'samgov_attachments';
        const safe = title.replace(/\s*\|\s*SAM\.gov.*$/i, '').replace(/[^a-z0-9._ -]+/ig, '_').trim();
        return (safe || 'samgov_attachments') + '.zip';
    }

    function clearCaptures() {
        state.captures = [];
        state.seen.clear();
        state.latestUrl = '';
        state.latestSource = '';
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
            'width:390px',
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
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:8px;">
                <button id="samzip-click">Click Download All</button>
                <button id="samzip-download">Download Latest</button>
                <button id="samzip-copy">Copy Latest URL</button>
                <button id="samzip-clear">Clear</button>
            </div>
            <textarea id="samzip-latest" readonly style="box-sizing:border-box;width:100%;height:82px;font-size:11px;resize:vertical;"></textarea>
            <div id="samzip-list" style="margin-top:8px;max-height:120px;overflow:auto;border-top:1px solid #374151;padding-top:6px;"></div>
        `;

        document.documentElement.appendChild(panel);
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
        const latest = document.getElementById('samzip-latest');
        const list = document.getElementById('samzip-list');
        if (!status || !latest || !list) return;

        if (state.latestUrl) {
            status.innerHTML = `Captured <b>${state.captures.length}</b> ZIP URL(s). Latest source: <b>${escapeHtml(state.latestSource)}</b>. Clicked Download All: <b>${state.clickCount}</b>.`;
            latest.value = state.latestUrl;
        } else {
            status.innerHTML = `Waiting for ZIP URL. Click the page's <b>Download All Attachments/Links</b> button or use <b>Click Download All</b>. Clicked: <b>${state.clickCount}</b>.`;
            latest.value = '';
        }

        list.innerHTML = state.captures.slice(0, 10).map((item, index) => {
            return `<div style="margin-bottom:6px;word-break:break-all;"><b>#${index + 1}</b> ${escapeHtml(item.source)}<br><a href="${escapeAttr(item.url)}" target="_blank" style="color:#93c5fd;">${escapeHtml(item.url)}</a></div>`;
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
