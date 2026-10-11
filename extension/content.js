/**
 * Second Opinion — ChatGPT Content Script
 * Detects completed assistant responses and injects an 'Audit with Second Opinion' button.
 */

(function () {
  'use strict';

  const DEFAULT_TARGET_URL = 'http://localhost:5173';
  const BUTTON_CLASS = 'so-audit-btn';
  const CONTAINER_CLASS = 'so-audit-container';

  /**
   * Extract clean text from an assistant message element,
   * excluding buttons, toolbars, and metadata.
   */
  function extractAssistantText(messageElem) {
    const markdownContainer = messageElem.querySelector('.markdown, .prose') || messageElem;

    // Clone node so we can safely remove non-content elements before getting text
    const clone = markdownContainer.cloneNode(true);

    // Remove any audit buttons or action toolbars from the clone
    const buttons = clone.querySelectorAll(`.${CONTAINER_CLASS}, button, svg, [role="toolbar"]`);
    buttons.forEach((b) => b.remove());

    return clone.innerText ? clone.innerText.trim() : '';
  }

  /**
   * Create the Second Opinion Audit Button element.
   */
  function createAuditButton(replyText) {
    const container = document.createElement('div');
    container.className = CONTAINER_CLASS;

    const button = document.createElement('button');
    button.type = 'button';
    button.className = BUTTON_CLASS;
    button.setAttribute('title', 'Audit and verify this response with Second Opinion');
    button.innerHTML = '<span class="so-glyph">◈</span> <span>Audit with Second Opinion</span>';

    button.addEventListener('click', (e) => {
      e.stopPropagation();
      e.preventDefault();

      if (!replyText || replyText.length < 5) {
        button.innerText = '⚠ No text found';
        setTimeout(() => {
          button.innerHTML = '<span class="so-glyph">◈</span> <span>Audit with Second Opinion</span>';
        }, 2000);
        return;
      }

      button.classList.add('so-loading');
      button.innerHTML = '<span class="so-glyph">✓</span> <span>Opening Second Opinion...</span>';

      chrome.storage.sync.get({ targetUrl: DEFAULT_TARGET_URL }, (data) => {
        const baseUrl = (data.targetUrl || DEFAULT_TARGET_URL).replace(/\/+$/, '');
        const redirectUrl = `${baseUrl}/#audit=${encodeURIComponent(replyText)}`;
        window.open(redirectUrl, '_blank');

        setTimeout(() => {
          button.classList.remove('so-loading');
          button.innerHTML = '<span class="so-glyph">◈</span> <span>Audit with Second Opinion</span>';
        }, 2500);
      });
    });

    container.appendChild(button);
    return container;
  }

  /**
   * Scan page and inject Audit buttons on ChatGPT assistant messages.
   */
  function injectAuditButtons() {
    // Select assistant messages across ChatGPT DOM structure variants
    const assistantSelectors = [
      '[data-message-author-role="assistant"]',
      'article[data-testid*="conversation-turn"]:has([data-message-author-role="assistant"])',
      'div.agent-turn',
    ];

    const assistantMessages = document.querySelectorAll(assistantSelectors.join(', '));

    assistantMessages.forEach((turn) => {
      // Avoid injecting multiple buttons
      if (turn.querySelector(`.${CONTAINER_CLASS}`)) {
        return;
      }

      // Check if message is currently streaming (skip until completed)
      if (turn.querySelector('.result-streaming, .streaming, [class*="streaming"]')) {
        return;
      }

      const text = extractAssistantText(turn);
      if (!text || text.length < 5) {
        return;
      }

      const btnContainer = createAuditButton(text);

      // Preferred placement: find the message action bar (copy/regenerate buttons) or append after text
      const actionsBar = turn.querySelector(
        '[class*="items-center"][class*="gap-"], .message-actions, [role="toolbar"], div.mt-2.flex'
      );

      if (actionsBar && actionsBar.parentNode) {
        actionsBar.parentNode.insertBefore(btnContainer, actionsBar.nextSibling);
      } else {
        const prose = turn.querySelector('.markdown, .prose') || turn;
        prose.appendChild(btnContainer);
      }
    });
  }

  // Debounced execution for MutationObserver
  let debounceTimeout = null;
  function triggerScan() {
    if (debounceTimeout) clearTimeout(debounceTimeout);
    debounceTimeout = setTimeout(injectAuditButtons, 300);
  }

  // Initial execution
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', triggerScan);
  } else {
    triggerScan();
  }

  // Observe ongoing chat conversations and streaming completions
  const observer = new MutationObserver(() => {
    triggerScan();
  });

  observer.observe(document.body, {
    childList: true,
    subtree: true,
  });
})();
