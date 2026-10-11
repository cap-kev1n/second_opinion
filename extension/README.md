# Second Opinion — ChatGPT Chrome Extension

Audit AI responses from ChatGPT in one click.

## Features
- **One-Click Audit**: Injects a sleek `◈ Audit with Second Opinion` button directly beside the Copy icon under each ChatGPT response.
- **Floating Fallback**: If ChatGPT layout changes, a floating `◈ AUDIT LATEST AI RESPONSE` button stays anchored at the bottom-right so you're never without an audit trigger.
- **Auto-Paste**: Redirects to Second Opinion and automatically pastes the AI reply into the audit terminal.
- **Zero-Upload Autonomous Mode**: Defaults to autonomous cross-checking so you can audit immediately with `Ctrl+Enter`.
- **Configurable Endpoint**: Set your local URL (`http://localhost:5173`) or your deployed Vercel production URL anytime from the extension popup.

---

## Installation / Update Steps

1. Open Google Chrome.
2. Navigate to `chrome://extensions`.
3. Enable **Developer mode** (toggle in the top-right corner).
4. Click **Load unpacked** (or click the **↻ Reload** button on the extension if already loaded).
5. Select the folder:
   ```
   d:\SO\bitnbuild\extension
   ```
6. **IMPORTANT**: Refresh (`F5`) any existing [ChatGPT](https://chatgpt.com) tabs! Chrome content scripts only attach to pages loaded or refreshed *after* the extension is installed/reloaded.

---

## How to Verify in ChatGPT

1. Go to [ChatGPT](https://chatgpt.com) and ask any question.
2. Look directly below the AI's reply:
   - Beside the Copy button toolbar, you will see: `◈ AUDIT WITH SECOND OPINION`.
   - At the bottom-right of the screen, you will also see the floating: `◈ AUDIT LATEST AI RESPONSE`.
3. Open F12 DevTools Console if needed: you will see `[Second Opinion Extension] Content script initialized on https://chatgpt.com`.
4. Click either button: Second Opinion opens in a new tab with the answer already pre-filled and ready to audit!
