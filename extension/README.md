# Second Opinion — ChatGPT Chrome Extension

Audit AI responses from ChatGPT in one click.

## Features
- **One-Click Audit**: Injects a sleek `◈ Audit with Second Opinion` button directly below ChatGPT assistant responses.
- **Auto-Paste**: When clicked, redirects to your Second Opinion web app and automatically pre-populates the AI reply into the audit terminal.
- **Autonomous AI Cross-Check**: Defaults to zero-upload autonomous cross-checking so you can audit immediately with `Ctrl+Enter`.
- **Configurable Endpoint**: Easily switch between your local dev server (`http://localhost:5173`) and your deployed Vercel production URL from the extension popup.

---

## Installation (Unpacked Extension)

1. Open Google Chrome (or any Chromium browser such as Brave, Edge, Opera).
2. Navigate to `chrome://extensions`.
3. Enable **Developer mode** using the toggle switch in the top-right corner.
4. Click **Load unpacked** in the top-left corner.
5. Select the `extension` folder inside this repository:
   ```
   d:\SO\bitnbuild\extension
   ```
6. The extension **Second Opinion — ChatGPT AI Auditor** is now installed!

---

## Usage

1. Open [ChatGPT](https://chatgpt.com) and ask any question.
2. Underneath the AI's reply, you will see the **`◈ Audit with Second Opinion`** button.
3. Click it — Second Opinion opens in a new tab with the AI answer already loaded in the terminal.
4. Hit **`Ctrl+Enter`** or click **`Cross-Check & Audit with AI`** to review the factual verdict specimen report!
