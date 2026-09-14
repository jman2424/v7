"use strict";

const examples = {
  product: ["I need a desk lamp for a small home office.", "Happy to help. The compact Studio Lamp could be a good fit. Do you prefer warm light for evenings or a brighter light for focused work?"],
  delivery: ["Can you help me check delivery?", "Of course. Which area would you like it delivered to? I can use the store’s delivery information to help you check the options before you decide."],
  handoff: ["I’m buying lamps for the whole team. Who can help?", "For a larger order, the store team can help you with the details. Would you like the store’s contact information so you can discuss quantities and requirements?"]
};

document.querySelectorAll("[data-example]").forEach((button) => {
  button.addEventListener("click", () => {
    const [question, answer] = examples[button.dataset.example];
    document.getElementById("sample-question").textContent = question;
    document.getElementById("sample-answer").textContent = answer;
    document.querySelectorAll("[data-example]").forEach((item) => {
      item.setAttribute("aria-pressed", String(item === button));
    });
  });
});
