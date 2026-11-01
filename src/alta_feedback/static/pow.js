// Проверка от ботов (proof-of-work в формате ALTCHA): браузер подбирает число, пока
// человек заполняет форму. Ни запросов наружу, ни cookie — задача уже лежит в странице.
(() => {
  const box = document.getElementById("pow");
  const field = document.querySelector("input[name=altcha]");
  const status = document.getElementById("pow-status");
  const form = box && box.closest("form");
  if (!box || !field || !form) return;

  const { algorithm, challenge, salt, signature } = box.dataset;
  const maxnumber = Number(box.dataset.maxnumber);
  const encoder = new TextEncoder();
  const BATCH = 500;
  let solved = false;
  let submitWhenDone = false;

  const hex = (buffer) => [...new Uint8Array(buffer)].map((b) => b.toString(16).padStart(2, "0")).join("");
  const digest = async (number) => hex(await crypto.subtle.digest("SHA-256", encoder.encode(salt + number)));

  const setStatus = (text, state) => {
    status.textContent = text;
    box.dataset.state = state;
  };

  const solve = async () => {
    for (let start = 0; start <= maxnumber; start += BATCH) {
      const numbers = [];
      for (let n = start; n < Math.min(start + BATCH, maxnumber + 1); n += 1) numbers.push(n);
      const hashes = await Promise.all(numbers.map(digest));
      const index = hashes.indexOf(challenge);
      if (index >= 0) return numbers[index];
    }
    return null;
  };

  form.addEventListener("submit", (event) => {
    if (solved) return;
    event.preventDefault();
    submitWhenDone = true;
    setStatus("Секунду, заканчиваем проверку…", "working");
  });

  if (!window.crypto || !crypto.subtle) {
    setStatus("Браузер не умеет проверку — откройте страницу в Chrome или Safari.", "error");
    return;
  }

  setStatus("Проверка от ботов…", "working");
  solve().then((number) => {
    if (number === null) {
      setStatus("Проверка не прошла — обновите страницу.", "error");
      return;
    }
    field.value = btoa(JSON.stringify({ algorithm, challenge, number, salt, signature }));
    solved = true;
    setStatus("Проверка от ботов пройдена", "done");
    if (submitWhenDone) form.requestSubmit ? form.requestSubmit() : form.submit();
  });
})();
