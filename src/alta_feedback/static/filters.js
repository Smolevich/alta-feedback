// Фильтры сводки: списки с поиском вместо системных <select> и поля дат в стиле страницы.
// Без скрипта форма работает на тех же <select> и <input type=date> с теми же name.
(() => {
  // Кириллицу сводим к латинице по-сербски: тогда «бел», «bel», «ниш» и «niš» находят свои города.
  const LATIN = {
    а: "a", б: "b", в: "v", г: "g", д: "d", ђ: "dj", е: "e", ж: "z", з: "z", и: "i", ј: "j",
    к: "k", л: "l", љ: "lj", м: "m", н: "n", њ: "nj", о: "o", п: "p", р: "r", с: "s", т: "t",
    ћ: "c", у: "u", ф: "f", х: "h", ц: "c", ч: "c", џ: "dz", ш: "s", щ: "s", ъ: "", ы: "y",
    ь: "", э: "e", ю: "ju", я: "ja",
  };

  /** Строка для сравнения: без регистра, диакритики, пробелов и дефисов, кириллица — латиницей. */
  const fold = (text) =>
    [...text.toLocaleLowerCase("ru").replaceAll("đ", "dj").normalize("NFD").replace(/\p{M}/gu, "")]
      .map((char) => LATIN[char] ?? char)
      .join("")
      .replace(/[^\p{L}\p{N}]+/gu, "");

  /** Варианты, где запрос встречается в подписи или в коде; пустой запрос — все варианты. */
  const filterOptions = (options, query) => {
    const needle = fold(query);
    if (!needle) return options;
    return options.filter((option) => option.value && [option.label, option.value].some((text) => fold(text).includes(needle)));
  };

  const make = (tag, className, props = {}) => Object.assign(document.createElement(tag), { className, ...props });

  // Видимая часть экрана: на телефоне её съедает клавиатура, а сверху — липкая шапка сайта.
  const visibleArea = () => {
    const view = window.visualViewport;
    const top = view ? view.offsetTop : 0;
    return { top: top + 64, bottom: top + (view ? view.height : window.innerHeight) };
  };

  // Подсветка набранного в подписи, если оно там есть буквально (иначе совпадение через транслит).
  const labelWithMatch = (label, query) => {
    const at = query ? label.toLocaleLowerCase("ru").indexOf(query.trim().toLocaleLowerCase("ru")) : -1;
    if (at < 0 || !query.trim()) return [label];
    const end = at + query.trim().length;
    return [label.slice(0, at), make("mark", "", { textContent: label.slice(at, end) }), label.slice(end)];
  };

  let comboCount = 0;

  const enhanceSelect = (select) => {
    const options = [...select.options].map((option) => ({ value: option.value, label: option.textContent.trim() }));
    const everything = options.find((option) => !option.value);
    const listId = `combo-list-${++comboCount}`;
    const box = make("div", "combo");
    const input = make("input", "combo-input", {
      type: "text", id: select.id, autocomplete: "off", spellcheck: false,
      placeholder: everything ? everything.label : "",
    });
    Object.entries({
      role: "combobox", "aria-autocomplete": "list", "aria-expanded": "false", "aria-controls": listId,
      autocapitalize: "off", enterkeyhint: "done",
    }).forEach(([name, value]) => input.setAttribute(name, value));
    const clear = make("button", "combo-clear", { type: "button", tabIndex: -1, hidden: true });
    clear.setAttribute("aria-label", "Сбросить");
    const list = make("ul", "combo-list", { id: listId, hidden: true });
    list.setAttribute("role", "listbox");
    select.removeAttribute("id");
    select.hidden = true;
    select.tabIndex = -1;
    box.append(input, clear, list);
    select.before(box);

    let shown = [];
    let active = -1;

    const current = () => options.find((option) => option.value === select.value) || everything;
    const showCurrent = () => {
      const option = current();
      input.value = option && option.value ? option.label : "";
      box.classList.toggle("chosen", Boolean(select.value));
      clear.hidden = !select.value;
    };

    const highlight = (index) => {
      active = index;
      [...list.children].forEach((item, i) => item.classList.toggle("active", i === index));
      const item = list.children[index];
      if (item && item.id) {
        input.setAttribute("aria-activedescendant", item.id);
        item.scrollIntoView({ block: "nearest" });
      } else {
        input.removeAttribute("aria-activedescendant");
      }
    };

    const place = () => {
      const area = visibleArea();
      const rect = input.getBoundingClientRect();
      const below = area.bottom - rect.bottom - 8;
      const above = rect.top - area.top - 8;
      const up = below < 200 && above > below;
      list.classList.toggle("up", up);
      list.style.maxHeight = `${Math.max(120, Math.min(340, up ? above : below))}px`;
      list.classList.remove("end");
      if (list.getBoundingClientRect().right > document.documentElement.clientWidth - 8) list.classList.add("end");
    };

    const render = (query) => {
      shown = filterOptions(options, query);
      const items = shown.map((option, i) => {
        const item = make("li", "combo-option", { id: `${listId}-${i}` });
        item.setAttribute("role", "option");
        item.setAttribute("aria-selected", String(option.value === select.value));
        item.append(...labelWithMatch(option.label, query));
        if (!option.value) item.classList.add("all");
        item.addEventListener("click", () => pick(option));
        return item;
      });
      if (!items.length) {
        const empty = make("li", "combo-empty", { textContent: "Ничего не нашлось" });
        empty.setAttribute("aria-disabled", "true");
        items.push(empty);
      }
      list.replaceChildren(...items);
      return shown;
    };

    const open = (query = "") => {
      render(query);
      list.hidden = false;
      box.classList.add("open");
      input.setAttribute("aria-expanded", "true");
      place();
      const selectedIndex = shown.findIndex((option) => option.value === select.value);
      highlight(query ? (shown.length ? 0 : -1) : selectedIndex);
    };

    const close = () => {
      list.hidden = true;
      box.classList.remove("open");
      input.setAttribute("aria-expanded", "false");
      input.removeAttribute("aria-activedescendant");
      active = -1;
    };

    // Ушёл, не выбрав: в поле возвращается то, что реально выбрано, а не набранный обрывок.
    const dismiss = () => {
      close();
      showCurrent();
    };

    const pick = (option) => {
      select.value = option.value;
      select.dispatchEvent(new Event("change", { bubbles: true }));
      dismiss();
    };

    const narrow = () => window.matchMedia("(max-width: 719px)").matches;

    input.addEventListener("focus", () => {
      // На телефоне поднимаем поле к шапке, чтобы список поместился над клавиатурой.
      if (narrow()) (box.closest(".field") || box).scrollIntoView({ block: "start" });
      open();
      input.select();
    });
    input.addEventListener("click", () => { if (list.hidden) open(); });
    input.addEventListener("input", () => open(input.value));
    input.addEventListener("keydown", (event) => {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        if (list.hidden) open();
        const step = event.key === "ArrowDown" ? 1 : -1;
        if (shown.length) highlight((active + step + shown.length) % shown.length);
      } else if (event.key === "Enter" && !list.hidden) {
        event.preventDefault();
        if (active >= 0 && shown[active]) pick(shown[active]);
        else if (!input.value.trim() && everything) pick(everything);
      } else if (event.key === "Escape" && !list.hidden) {
        event.preventDefault();
        dismiss();
      } else if (event.key === "Tab") {
        dismiss();
      }
    });
    // Список не забирает фокус у поля, иначе на компьютере клик по варианту закрыл бы его раньше выбора.
    list.addEventListener("mousedown", (event) => event.preventDefault());
    clear.addEventListener("mousedown", (event) => event.preventDefault());
    clear.addEventListener("click", () => {
      if (everything) pick(everything);
      input.focus();
    });
    box.addEventListener("focusout", (event) => {
      if (event.relatedTarget && !box.contains(event.relatedTarget)) dismiss();
    });
    document.addEventListener("pointerdown", (event) => {
      if (!list.hidden && !box.contains(event.target)) dismiss();
    });
    window.visualViewport?.addEventListener("resize", () => { if (!list.hidden) place(); });
    window.addEventListener("pageshow", showCurrent);
    showCurrent();
  };

  const CALENDAR_ICON =
    '<svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true"><rect x="2.5" y="4" width="15" height="13" rx="1.5" ' +
    'fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M2.5 8h15M6.5 2v4M13.5 2v4" stroke="currentColor" ' +
    'stroke-width="1.6" stroke-linecap="round"/></svg>';

  /** 2026-10-12 → 12.10.2026; пусто или не дата — пустая строка. */
  const russianDate = (iso) => {
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || "");
    return match ? `${match[3]}.${match[2]}.${match[1]}` : "";
  };

  // Системный выбор даты на телефоне удобен, поэтому оставляем его, но прячем под поле в стиле страницы.
  const enhanceDate = (input) => {
    const box = make("div", "date");
    const face = make("span", "date-face");
    face.setAttribute("aria-hidden", "true");
    const icon = make("span", "date-icon", { innerHTML: CALENDAR_ICON });
    const clear = make("button", "date-clear", { type: "button", hidden: true });
    clear.setAttribute("aria-label", "Очистить дату");
    input.before(box);
    box.append(icon, face, input, clear);
    input.classList.add("date-native");

    const show = () => {
      const text = russianDate(input.value);
      face.textContent = text || "дд.мм.гггг";
      box.classList.toggle("chosen", Boolean(text));
      clear.hidden = !text;
    };
    input.addEventListener("click", () => {
      try { input.showPicker(); } catch { /* старый браузер откроет выбор сам */ }
    });
    input.addEventListener("input", show);
    input.addEventListener("change", show);
    clear.addEventListener("click", () => {
      input.value = "";
      show();
      input.focus();
    });
    window.addEventListener("pageshow", show);
    show();
  };

  if (typeof module === "object" && module.exports) {
    module.exports = { fold, filterOptions, russianDate };
    return;
  }
  const form = document.querySelector("form.filters");
  if (!form) return;
  form.querySelectorAll("select").forEach(enhanceSelect);
  form.querySelectorAll("input[type=date]").forEach(enhanceDate);
  // Пустые поля не отправляем: ссылка на фильтр короче, её проще переслать.
  const named = () => [...form.querySelectorAll("select[name], input[name]")];
  form.addEventListener("submit", () => named().forEach((field) => { field.disabled = !field.value; }));
  window.addEventListener("pageshow", () => named().forEach((field) => { field.disabled = false; }));
})();
