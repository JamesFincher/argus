(() => {
  const payload = {
    type: "page_context",
    href: location.href,
    domain: location.hostname,
    title: document.title,
    selection: String(window.getSelection() || "")
  };

  browser.runtime.sendMessage(payload);
})();
