// Поля с подсказками: печатаешь — список фильтруется, можно выбрать или оставить своё.
// Без скрипта работают те же поля через <datalist>; скрипт нужен ради списка на телефоне
// (iOS показывает datalist неудобно) и тегов у документов.
(() => {
  const norm = (text) => text.trim().toLocaleLowerCase("ru");

  const optionsFor = (input) => {
    const list = document.getElementById(input.getAttribute("list"));
    return list ? [...list.options].map((option) => option.value) : [];
  };

  // Выпадающий список под полем; pick вызывается с выбранной строкой.
  const attachList = (input, options, pick, excluded) => {
    input.removeAttribute("list");
    input.setAttribute("role", "combobox");
    input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("aria-expanded", "false");
    const list = document.createElement("ul");
    list.className = "combo-list";
    list.setAttribute("role", "listbox");
    list.id = `${input.id}-options`;
    list.hidden = true;
    input.setAttribute("aria-controls", list.id);
    input.parentElement.append(list);
    let shown = [];
    let active = -1;

    const close = () => {
      list.hidden = true;
      input.setAttribute("aria-expanded", "false");
      active = -1;
    };

    const highlight = (index) => {
      active = index;
      [...list.children].forEach((item, i) => item.classList.toggle("active", i === index));
      if (list.children[index]) list.children[index].scrollIntoView({ block: "nearest" });
    };

    const render = (showAll) => {
      const query = showAll ? "" : norm(input.value);
      const skip = excluded();
      shown = options.filter((option) => !skip.includes(option) && norm(option).includes(query));
      const typed = input.value.trim();
      const exact = options.some((option) => norm(option) === norm(typed));
      const items = shown.map((option) => ({ text: option, label: option }));
      if (typed && !exact && excluded !== noExclusions) items.push({ text: typed, label: `Добавить «${typed}»`, custom: true });
      list.replaceChildren(...items.map((item) => {
        const li = document.createElement("li");
        li.setAttribute("role", "option");
        li.textContent = item.label;
        if (item.custom) li.className = "custom";
        // pointerdown, а не click: иначе blur поля закроет список раньше выбора.
        li.addEventListener("pointerdown", (event) => { event.preventDefault(); pick(item.text); });
        return li;
      }));
      shown = items.map((item) => item.text);
      list.hidden = items.length === 0;
      input.setAttribute("aria-expanded", String(!list.hidden));
      active = -1;
    };

    input.addEventListener("focus", () => render(true));
    input.addEventListener("click", () => { if (list.hidden) render(true); });
    input.addEventListener("input", () => render(false));
    input.addEventListener("blur", close);
    input.addEventListener("keydown", (event) => {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        if (list.hidden) render(true);
        const step = event.key === "ArrowDown" ? 1 : -1;
        highlight(Math.max(0, Math.min(shown.length - 1, active + step)));
      } else if (event.key === "Enter" && !list.hidden && (active >= 0 || excluded !== noExclusions)) {
        event.preventDefault();
        if (active >= 0) pick(shown[active]);
        else if (input.value.trim()) pick(input.value.trim());
      } else if (event.key === "Escape") {
        close();
      }
    });
    return { render, close };
  };

  const noExclusions = () => [];

  const single = (input) => {
    const options = optionsFor(input);
    const control = attachList(input, options, (value) => {
      input.value = value;
      control.close();
    }, noExclusions);
  };

  const multi = (input, box) => {
    const name = box.dataset.multi;
    const tags = box.querySelector(".tags");
    const options = optionsFor(input);
    const chosen = () => [...tags.querySelectorAll("input[type=hidden]")].map((hidden) => hidden.value);

    const addTag = (value) => {
      const text = value.trim();
      if (!text || chosen().some((existing) => norm(existing) === norm(text))) return;
      const tag = document.createElement("span");
      tag.className = "tag";
      const hidden = Object.assign(document.createElement("input"), { type: "hidden", name, value: text });
      const remove = Object.assign(document.createElement("button"), { type: "button", textContent: "×" });
      remove.setAttribute("aria-label", `Убрать: ${text}`);
      remove.addEventListener("click", () => { tag.remove(); input.focus(); });
      tag.append(text, hidden, remove);
      tags.append(tag);
    };

    // Значения, вернувшиеся с сервера после ошибки, превращаем в теги.
    const restored = chosen();
    tags.replaceChildren();
    restored.forEach(addTag);

    input.removeAttribute("name");
    const control = attachList(input, options, (value) => {
      addTag(value);
      input.value = "";
      control.render(true);
    }, chosen);
    // Напечатал своё и ушёл из поля — не теряем.
    input.addEventListener("change", () => {
      if (input.value.trim()) { addTag(input.value); input.value = ""; }
    });
  };

  document.querySelectorAll("input[data-combo]").forEach((input) => {
    const box = input.closest("[data-multi]");
    if (box) multi(input, box);
    else single(input);
  });
})();
