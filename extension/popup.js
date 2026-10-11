document.addEventListener('DOMContentLoaded', () => {
  const targetUrlInput = document.getElementById('targetUrl');
  const saveBtn = document.getElementById('saveBtn');
  const openAppBtn = document.getElementById('openAppBtn');
  const statusMsg = document.getElementById('statusMsg');

  const DEFAULT_URL = 'http://localhost:5173';

  // Load saved URL or default
  chrome.storage.sync.get({ targetUrl: DEFAULT_URL }, (data) => {
    targetUrlInput.value = data.targetUrl || DEFAULT_URL;
  });

  saveBtn.addEventListener('click', () => {
    const rawUrl = targetUrlInput.value.trim() || DEFAULT_URL;
    chrome.storage.sync.set({ targetUrl: rawUrl }, () => {
      statusMsg.textContent = '✓ Target URL saved successfully!';
      setTimeout(() => {
        statusMsg.textContent = '';
      }, 2500);
    });
  });

  openAppBtn.addEventListener('click', () => {
    const url = targetUrlInput.value.trim() || DEFAULT_URL;
    window.open(url, '_blank');
  });
});
