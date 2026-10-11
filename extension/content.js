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
  /**
   * Extract clean visible text from an attached DOM element.
   * Uses live node.innerText (avoids disconnected clone.innerText Chromium blank issues).
   */
  function extractCleanText(node) {
    if (!node) return '';
    try {
      // If node is already a markdown/prose text block, its innerText is pristine
      if (node.matches && (node.matches('.markdown, .prose, [class*="markdown"]') || node.tagName === 'P')) {
        const txt = (node.innerText || node.textContent || '').trim();
        if (txt) return txt;
      }

      // If the node has markdown children, extract from those first
      const mdChild = node.querySelector?.('.markdown, .prose, [class*="markdown"], div[class*="text-message"]');
      if (mdChild) {
        const mdText = (mdChild.innerText || mdChild.textContent || '').trim();
        if (mdText.length > 5) return mdText;
      }

      // Collect paragraphs and code blocks if present
      const paragraphs = node.querySelectorAll?.('p, pre, li, blockquote, h1, h2, h3, h4, h5, h6');
      if (paragraphs && paragraphs.length > 0) {
        const parts = [];
        paragraphs.forEach((p) => {
          if (!p.closest(`.${CONTAINER_CLASS}, #${FLOATING_BTN_ID}, [role="toolbar"], button`)) {
            const pTxt = (p.innerText || p.textContent || '').trim();
            if (pTxt) parts.push(pTxt);
          }
        });
        if (parts.length > 0) {
          return parts.join('\n\n').trim();
        }
      }

      // Fallback: take innerText directly
      const rawText = (node.innerText || node.textContent || '').trim();
      return rawText;
    } catch (err) {
      console.error('[Second Opinion Extension] extractCleanText error:', err);
      return (node.innerText || node.textContent || '').trim();
    }
  }

  /**
   * Resilient assistant text locator. Starts from clicked button and
   * navigates ChatGPT DOM hierarchies (including new 2024-2026 designs).
   */
  function findAssistantTextFromButton(btn) {
    console.log('[Second Opinion Extension] Initiating text extraction from button...');

    // 1. If user explicitly selected / highlighted text, prioritize selection
    const selection = window.getSelection()?.toString()?.trim();
    if (selection && selection.length > 5) {
      console.log('[Second Opinion Extension] Found active user selection:', selection.length, 'chars');
      return selection;
    }

    // 2. Check enclosing article, conversation turn, or assistant role container
    const turnContainer = btn.closest(
      'article, [data-message-author-role="assistant"], div.agent-turn, [data-testid*="conversation-turn"], div[class*="conversation-turn"]'
    );
    if (turnContainer) {
      console.log('[Second Opinion Extension] Found turn container:', turnContainer.tagName, turnContainer.className);
      const text = extractCleanText(turnContainer);
      if (text && text.length > 5) {
        console.log('[Second Opinion Extension] Extracted text from turn container:', text.length, 'chars');
        return text;
      }
    }

    // 3. Ascend ancestors and inspect previous sibling elements (ChatGPT places action bar directly after markdown)
    let curr = btn;
    for (let depth = 0; depth < 12 && curr && curr !== document.body; depth++) {
      let prev = curr.previousElementSibling;
      while (prev) {
        // Direct or descendant markdown/prose check
        const md = prev.matches?.('.markdown, .prose, [class*="markdown"], [class*="prose"], div[class*="text-message"]')
          ? prev
          : prev.querySelector?.('.markdown, .prose, [class*="markdown"], [class*="prose"], div[class*="text-message"]');

        if (md) {
          const text = extractCleanText(md);
          if (text && text.length > 5) {
            console.log('[Second Opinion Extension] Extracted text from previous sibling markdown:', text.length, 'chars');
            return text;
          }
        }

        const prevText = extractCleanText(prev);
        if (prevText && prevText.length > 15) {
          console.log('[Second Opinion Extension] Extracted text from previous sibling:', prevText.length, 'chars');
          return prevText;
        }

        prev = prev.previousElementSibling;
      }
      curr = curr.parentElement;
    }

    // 4. Check all markdown containers on the page (choose the one closest to the clicked button)
    const allMarkdown = Array.from(
      document.querySelectorAll('.markdown, div[class*="markdown"], div.prose, [data-message-author-role="assistant"]')
    ).filter((el) => !el.closest('form, #prompt-textarea, [contenteditable="true"]'));

    if (allMarkdown.length > 0) {
      // If button has a bounding rect, find the markdown whose bottom is immediately above the button
      const btnRect = btn.getBoundingClientRect();
      let bestMatch = null;
      let minDistance = Infinity;

      for (const md of allMarkdown) {
        const mdRect = md.getBoundingClientRect();
        // Assistant text should be vertically at or above the button
        const diff = btnRect.top - mdRect.bottom;
        if (diff >= -50 && diff < minDistance) {
          minDistance = diff;
          bestMatch = md;
        }
      }

      if (bestMatch) {
        const text = extractCleanText(bestMatch);
        if (text && text.length > 5) {
          console.log('[Second Opinion Extension] Extracted text from proximity matched markdown:', text.length, 'chars');
          return text;
        }
      }

      // Default to the last assistant markdown on page
      const lastMd = allMarkdown[allMarkdown.length - 1];
      const text = extractCleanText(lastMd);
      if (text && text.length > 5) {
        console.log('[Second Opinion Extension] Fallback: Extracted text from latest markdown on page:', text.length, 'chars');
        return text;
      }
    }

    console.warn('[Second Opinion Extension] Could not locate any assistant text.');
    return '';
  }

  /**
   * Redirect user to Second Opinion with the text payload.
   */
  function triggerAudit(text, btnElement) {
    console.log('[Second Opinion Extension] triggerAudit called. Text length:', text ? text.length : 0);

    if (!text || text.length < 5) {
      console.warn('[Second Opinion Extension] Text detection failed or text too short.');
      if (btnElement) {
        const originalHtml = btnElement.innerHTML;
        btnElement.innerText = '⚠ No text detected';
        setTimeout(() => {
          btnElement.innerHTML = originalHtml;
        }, 2200);
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
      console.log('[Second Opinion Extension] Opening redirect URL:', redirectUrl.slice(0, 80) + '...');
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
  function createAuditButton() {
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
      const text = findAssistantTextFromButton(btn);
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
    const copyButtons = document.querySelectorAll(
      'button[aria-label*="Copy" i], button[data-testid*="copy" i], button[title*="Copy" i]'
    );

    copyButtons.forEach((copyBtn) => {
      const toolbar = copyBtn.closest('[class*="items-center"], [role="toolbar"], .flex') || copyBtn.parentElement;
      if (!toolbar) return;

      // Skip if already has audit button
      if (toolbar.querySelector(`.${CONTAINER_CLASS}`) || toolbar.parentElement?.querySelector(`.${CONTAINER_CLASS}`)) {
        return;
      }

      const btnContainer = createAuditButton();
      toolbar.appendChild(btnContainer);
      injected++;
    });

    // Strategy 2: Find all .markdown containers
    const markdownContainers = document.querySelectorAll('.markdown, div[class*="markdown"], div.prose');
    markdownContainers.forEach((md) => {
      if (md.closest('form, #prompt-textarea, [contenteditable="true"]')) return;

      const parentTurn = md.closest('article, [data-message-author-role="assistant"], div.agent-turn') || md.parentElement;
      if (!parentTurn) return;

      if (parentTurn.querySelector(`.${CONTAINER_CLASS}`)) return;

      // Skip if still streaming
      if (parentTurn.querySelector('.result-streaming, .streaming, [class*="streaming"]')) return;

      const btnContainer = createAuditButton();
      if (md.nextSibling) {
        md.parentNode.insertBefore(btnContainer, md.nextSibling);
      } else {
        md.parentNode.appendChild(btnContainer);
      }
      injected++;
    });

    // Strategy 3: Global Floating "Audit Latest Response" Pill
    ensureFloatingAuditButton();

    if (injected > 0) {
      console.log(`[Second Opinion Extension] Injected audit button on ${injected} response(s).`);
    }
  }

  /**
   * Floating quick-action pill attached near the bottom-right corner.
   */
  function ensureFloatingAuditButton() {
    if (document.getElementById(FLOATING_BTN_ID)) return;

    const floatingBtn = document.createElement('button');
    floatingBtn.id = FLOATING_BTN_ID;
    floatingBtn.type = 'button';
    floatingBtn.className = 'so-floating-audit-btn';
    floatingBtn.innerHTML = '<span class="so-glyph">◈</span> <span>Audit Latest AI Response</span>';
    floatingBtn.setAttribute('title', 'Click to audit the most recent ChatGPT answer with Second Opinion');

    floatingBtn.addEventListener('click', (e) => {
      e.preventDefault();
      const text = findAssistantTextFromButton(floatingBtn);
      triggerAudit(text, floatingBtn);
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
