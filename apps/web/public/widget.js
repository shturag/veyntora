/*
 * Veyntora website widget. Paste on an allowed intranet page:
 *   <script src="https://<veyntora>/widget.js" data-bot="<chatbot short name>"
 *           data-position="bottom-right" data-theme="light" defer></script>
 * It adds a button that opens the chatbot in a frame. People sign in in a pop-up; the
 * chatbot only loads on the websites allowed on the Channels & API page.
 */
(function () {
  var script = document.currentScript;
  if (!script) return;
  var bot = script.getAttribute("data-bot");
  if (!bot || !/^[a-z0-9-]{2,64}$/.test(bot)) return;
  var base = new URL(script.src).origin;
  var left = script.getAttribute("data-position") === "bottom-left";
  var side = left ? "left" : "right";

  var button = document.createElement("button");
  button.type = "button";
  button.textContent = script.getAttribute("data-label") || "Ask";
  button.setAttribute("aria-expanded", "false");
  button.style.cssText =
    "position:fixed;bottom:20px;" + side + ":20px;z-index:2147483646;height:48px;padding:0 20px;" +
    "border:0;border-radius:24px;background:#3345B8;color:#fff;font:600 14px system-ui,sans-serif;" +
    "box-shadow:0 8px 24px rgba(0,0,0,.2);cursor:pointer";

  var frame = null;
  button.addEventListener("click", function () {
    if (!frame) {
      frame = document.createElement("iframe");
      frame.src = base + "/widget/" + encodeURIComponent(bot);
      frame.title = button.textContent;
      frame.setAttribute("allow", "clipboard-write");
      frame.style.cssText =
        "position:fixed;bottom:80px;" + side + ":20px;z-index:2147483647;width:380px;height:560px;" +
        "max-width:calc(100vw - 40px);max-height:calc(100vh - 100px);border:1px solid #E4E3DE;" +
        "border-radius:12px;background:#fff;box-shadow:0 24px 64px rgba(0,0,0,.25)";
      document.body.appendChild(frame);
    } else {
      frame.style.display = frame.style.display === "none" ? "block" : "none";
    }
    button.setAttribute("aria-expanded", String(frame.style.display !== "none"));
  });
  document.body.appendChild(button);
})();
