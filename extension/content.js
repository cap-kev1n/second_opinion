/**
 * Second Opinion — ChatGPT Content Script
 * Robustly injects an 'Audit with Second Opinion' button into ChatGPT responses.
 */

(function () {
  'use strict';

  console.log('[Second Opinion Extension] Content script initialized on', window.location.href);

  const DEFAULT_TARGET_URL = 'http://localhost:5173';
  const BTN_CLASS = 'so-audit-btn';
  const CONTAINER_CLASS = 'so-audit-container';
  const FLOATING_BTN_ID = 'so-floating-audit-btn';

  /**
   * Helper to retrieve clean reply text from a node or ancestor.
   */
  function getCleanText(element) {
    if (!element) return '';

    // Find the markdown or prose container
    const markdown = element.querySelector('.markdown, .prose, [class*="markdown"]') || element;
    const clone = markdown.cloneNode(true);

    // Remove buttons, toolbars, and our own audit UI
    clone.querySelectorAll(`.${CONTAINER_CLASS}, #${FLOATING_BTN_ID}, button, svg, [role="toolbar"]`).forEach(el => el.remove());

    return (clone.innerText || clone.textContent || '').trim();
  }

  /**
   * Redirect user to Second Opinion with the text payload.
   */
  function triggerAudit(text, btnElement) {
    if (!text || text.length < 5) {
      if (btnElement) {
        const originalHtml = btnElement.innerHTML;
        btnElement.innerText = '⚠ No text detected';
        setTimeout(() => { btnElement.innerHTML = originalHtml; }, 2000);
      }
      return;
    }

    if (btnElement) {
      btnElement.classList.add('so-loading');
      btnElement.innerHTML = '<span class="so-glyph">✓</span> <span>Opening Second Opinion...</span>';
    }

    chrome.storage.sync.get({ targetUrl: DEFAULT_TARGET_URL }, (data) => {
      const baseUrl = (data.targetUrl || DEFAULT_TARGET_URL).replace(/\/+$/, '');
      const redirectUrl = `${baseUrl}/#audit=${encodeURIComponent(text)}`;
      window.open(redirectUrl, '_blank');

      if (btnElement) {
        setTimeout(() => {
          btnElement.classList.remove('so-loading');
          btnElement.innerHTML = '<span class="so-glyph">◈</span> <span>Audit with Second Opinion</span>';
        }, 2000);
      }
    });
  }

  /**
   * Create the audit button element.
   */
  function createAuditButton(getTextFn) {
    const container = document.createElement('div');
    container.className = CONTAINER_CLASS;

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = BTN_CLASS;
    btn.setAttribute('title', 'Verify factual accuracy with Second Opinion');
    btn.innerHTML = '<span class="so-glyph">◈</span> <span>Audit with Second Opinion</span>';

    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      e.preventDefault();
      const text = getTextFn();
      triggerAudit(text, btn);
    });

    container.appendChild(btn);
    return container;
  }

  /**
   * Core scanner using multiple resilient strategies.
   */
  function scanAndInject() {
    let injected = 0;

    // Strategy 1: Find Copy Buttons in Action Toolbars
    // ChatGPT renders a Copy button below every assistant response.
    const copyButtons = document.querySelectorAll(
      'button[aria-label*="Copy" i], button[data-testid*="copy" i], button[title*="Copy" i]'
    );

    copyButtons.forEach((copyBtn) => {
      const toolbar = copyBtn.closest('[class*="items-center"], [role="toolbar"], .flex') || copyBtn.parentElement;
      if (!toolbar) return;

      // Check if already injected in this toolbar
      if (toolbar.querySelector(`.${CONTAINER_CLASS}`) || toolbar.parentElement?.querySelector(`.${CONTAINER_CLASS}`)) {
        return;
      }

      // Find message container above the toolbar
      const turnContainer = copyBtn.closest('article, [data-message-author-role="assistant"], div.agent-turn, [data-testid*="conversation-turn"]')
        || toolbar.closest('article')
        || toolbar.parentElement;

      const getText = () => getCleanText(turnContainer);
      const btn = createAuditButton(getText);

      // Insert directly after copy button or at the end of the toolbar
      toolbar.appendChild(btn);
      injected++;
    });

    // Strategy 2: Find all .markdown containers
    const markdownContainers = document.querySelectorAll('.markdown, div[class*="markdown"], div.prose');
    markdownContainers.forEach((md) => {
      // Ignore user input editor or message input
      if (md.closest('form, #prompt-textarea, [contenteditable="true"]')) return;

      const parentTurn = md.closest('article, [data-message-author-role="assistant"], div.agent-turn') || md.parentElement;
      if (!parentTurn) return;

      // If already has an audit button anywhere in this turn, skip
      if (parentTurn.querySelector(`.${CONTAINER_CLASS}`)) return;

      // Wait if currently streaming
      if (parentTurn.querySelector('.result-streaming, .streaming, [class*="streaming"]')) return;

      const getText = () => getCleanText(md);
      const btn = createAuditButton(getText);

      // Insert right after the markdown content
      if (md.nextSibling) {
        md.parentNode.insertBefore(btn, md.nextSibling);
      } else {
        md.parentNode.appendChild(btn);
      }
      injected++;
    });

    // Strategy 3: Global Floating "Audit Latest Response" Pill
    // Ensures user always has a guaranteed button even if ChatGPT updates its DOM classes
    ensureFloatingAuditButton();

    if (injected > 0) {
      console.log(`[Second Opinion Extension] Injected audit button on ${injected} response(s).`);
    }
  }

  /**
   * Floating quick-action pill attached near the bottom input bar.
   */
  function ensureFloatingAuditButton() {
    if (document.getElementById(FLOATING_BTN_ID)) return;

    // Find the chat input prompt form or textarea
    const promptForm = document.querySelector('form, #prompt-textarea')?.closest('form') || document.body;
    if (!promptForm) return;

    const floatingBtn = document.createElement('button');
    floatingBtn.id = FLOATING_BTN_ID;
    floatingBtn.type = 'button';
    floatingBtn.className = 'so-floating-audit-btn';
    floatingBtn.innerHTML = '<span class="so-glyph">◈</span> <span>Audit Latest AI Response</span>';
    floatingBtn.setAttribute('title', 'Click to audit the most recent ChatGPT answer with Second Opinion');

    floatingBtn.addEventListener('click', (e) => {
      e.preventDefault();
      // Find the last assistant message on the page
      const allMarkdown = document.querySelectorAll('.markdown, div[class*="markdown"], [data-message-author-role="assistant"]');
      let lastText = '';
      if (allMarkdown.length > 0) {
        lastText = getCleanText(allMarkdown[allMarkdown.length - 1]);
      }
      if (!lastText) {
        // Fallback: look for text in articles
        const articles = document.querySelectorAll('article');
        if (articles.length > 0) {
          lastText = getCleanText(articles[articles.length - 1]);
        }
      }
      triggerAudit(lastText, floatingBtn);
    });

    document.body.appendChild(floatingBtn);
  }

  // Periodic scan (every 1s) to handle dynamic SPA route changes & hydration
  setInterval(scanAndInject, 1000);

  // MutationObserver for immediate reactivity
  const observer = new MutationObserver(() => {
    scanAndInject();
  });

  observer.observe(document.body, {
    childList: true,
    subtree: true,
  });

  // Run on initial load
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', scanAndInject);
  } else {
    scanAndInject();
  }
})();
