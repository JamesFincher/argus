browser.runtime.onMessage.addListener((payload) => {
  if (!payload || payload.type !== "page_context") {
    return;
  }

  browser.runtime.sendNativeMessage("com.argus.sensor.native", payload);
});
