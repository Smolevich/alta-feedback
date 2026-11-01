// Подсказки поля «Отделение»: когда выбраны банк и город, берём отделения этого банка в этом
// городе из справочника на сервере. Без скрипта поле — обычный ввод текста.
(() => {
  const bank = document.getElementById("bank");
  const city = document.getElementById("city");
  const branch = document.getElementById("branch");
  const list = document.getElementById("branch-list");
  if (!bank || !city || !branch || !list) return;
  const notSure = list.options[0] ? list.options[0].value : "";
  const idle = branch.getAttribute("placeholder");
  let asked = "";

  const fill = (values) => {
    list.replaceChildren(...values.map((value) => Object.assign(document.createElement("option"), { value })));
    const found = values.filter((value) => value !== notSure).length;
    branch.setAttribute("placeholder", found ? `Выберите из ${found} или впишите` : idle);
  };

  const refresh = async () => {
    const query = new URLSearchParams({ bank: bank.value.trim(), city: city.value.trim() });
    const key = query.toString();
    if (key === asked) return;
    asked = key;
    if (!query.get("bank") || !query.get("city")) {
      fill([notSure]);
      return;
    }
    try {
      const response = await fetch(`/account/branches?${key}`);
      if (!response.ok || key !== asked) return;
      fill((await response.json()).branches);
    } catch {
      // Нет сети — остаётся свободный ввод.
    }
  };

  bank.addEventListener("change", refresh);
  city.addEventListener("change", refresh);
  refresh();
})();
