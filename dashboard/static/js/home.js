"use strict";

document.querySelectorAll('a[href="#demo"]').forEach((link) => {
  link.addEventListener("click", (event) => {
    const demo = document.getElementById("demo");
    if (!demo) return;
    event.preventDefault();
    demo.scrollIntoView({
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth",
      block: "start"
    });
    demo.querySelector("iframe, a")?.focus({ preventScroll: true });
  });
});

// "See it in action" opens the real customer widget in the corner of the page.
document.querySelectorAll('[data-open-assistant]').forEach(function (control) {
  control.addEventListener('click', function (event) {
    var root = document.querySelector('[id^="v7-widget-"][id$="-root"]');
    var launcher = root && root.querySelector('button');
    if (!launcher) return;
    event.preventDefault();
    var frame = root.querySelector('iframe');
    if (!frame || frame.style.display === 'none') launcher.click();
    launcher.focus();
  });
});
