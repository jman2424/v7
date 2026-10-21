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
