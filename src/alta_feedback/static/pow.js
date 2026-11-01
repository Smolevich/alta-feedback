// Проверка от ботов (proof-of-work в формате ALTCHA): по отметке «Я не робот» браузер
// подбирает число. Ни сторонних сервисов, ни cookie — задача уже лежит в странице.
(() => {
  const root = document.getElementById("pow");
  const box = document.getElementById("pow-box");
  const text = document.getElementById("pow-text");
  const hint = document.getElementById("pow-hint");
  const field = root && root.querySelector("input[name=altcha]");
  const form = root && root.closest("form");
  const button = form && form.querySelector("button[type=submit]");
  if (!root || !box || !text || !hint || !field || !form) return;

  const BATCH = 500;
  // Мелькнувший за долю секунды спиннер выглядит как сбой, а не как проверка.
  const MIN_VISIBLE_MS = 700;
  // Запас на дорогу до сервера: решение, отправленное за секунду до конца срока, уже не примут.
  const EXPIRY_MARGIN_MS = 20000;
  const encoder = new TextEncoder();
  const hex = (buffer) => [...new Uint8Array(buffer)].map((b) => b.toString(16).padStart(2, "0")).join("");

  const fromDataset = (data) => ({
    algorithm: data.algorithm, challenge: data.challenge, salt: data.salt, signature: data.signature,
    maxnumber: Number(data.maxnumber), ttl: Number(data.ttl),
  });
  // Срок считаем по своим часам от момента получения: часы телефона могут врать.
  const withDeadline = (task) => ({ ...task, deadline: Date.now() + task.ttl * 1000 - EXPIRY_MARGIN_MS });

  let task = withDeadline(fromDataset(root.dataset));
  let expiryTimer = null;
  let submitWhenDone = false;

  const setState = (state, label, message = "") => {
    root.dataset.state = state;
    text.textContent = label;
    hint.textContent = message;
    box.setAttribute("aria-checked", state === "done" ? "true" : "false");
    box.setAttribute("aria-busy", state === "working" ? "true" : "false");
    if (button) button.setAttribute("aria-disabled", state === "done" ? "false" : "true");
    if (state === "done" || state === "working") delete root.dataset.attention;
  };

  const solve = async ({ algorithm, challenge, salt, maxnumber }) => {
    if (algorithm !== "SHA-256") return null;
    const digest = async (n) => hex(await crypto.subtle.digest("SHA-256", encoder.encode(salt + n)));
    for (let start = 0; start <= maxnumber; start += BATCH) {
      const numbers = [];
      for (let n = start; n < Math.min(start + BATCH, maxnumber + 1); n += 1) numbers.push(n);
      const hashes = await Promise.all(numbers.map(digest));
      const index = hashes.indexOf(challenge);
      if (index >= 0) return numbers[index];
    }
    return null;
  };

  const freshTask = async () => {
    if (Date.now() < task.deadline) return task;
    const response = await fetch("/account/challenge", { cache: "no-store", credentials: "omit" });
    if (!response.ok) throw new Error(`challenge ${response.status}`);
    task = withDeadline(await response.json());
    return task;
  };

  const expire = () => {
    field.value = "";
    setState("idle", "Я не робот", "Проверка устарела — отметьте «Я не робот» ещё раз.");
    root.dataset.attention = "";
  };

  const verify = async () => {
    if (root.dataset.state === "working" || root.dataset.state === "done") return;
    if (!window.crypto || !crypto.subtle) {
      setState("error", "Я не робот", "Браузер не умеет проверку — откройте страницу в Chrome или Safari.");
      return;
    }
    setState("working", "Проверяем…");
    const started = performance.now();
    let current;
    let number = null;
    try {
      current = await freshTask();
      number = await solve(current);
    } catch {
      number = null;
    }
    const left = MIN_VISIBLE_MS - (performance.now() - started);
    if (left > 0) await new Promise((resolve) => setTimeout(resolve, left));
    if (number === null) {
      submitWhenDone = false;
      setState("error", "Я не робот", "Проверка не прошла — отметьте ещё раз или обновите страницу.");
      return;
    }
    const { algorithm, challenge, salt, signature } = current;
    field.value = btoa(JSON.stringify({ algorithm, challenge, number, salt, signature }));
    setState("done", "Проверено");
    clearTimeout(expiryTimer);
    expiryTimer = setTimeout(expire, Math.max(0, current.deadline - Date.now()));
    if (submitWhenDone) form.requestSubmit ? form.requestSubmit() : form.submit();
  };

  box.addEventListener("click", verify);
  box.addEventListener("keydown", (event) => {
    if (event.key !== " " && event.key !== "Enter") return;
    event.preventDefault();
    verify();
  });

  form.addEventListener("submit", (event) => {
    if (root.dataset.state === "done" && Date.now() < task.deadline) return;
    event.preventDefault();
    if (root.dataset.state === "working") {
      submitWhenDone = true;
      hint.textContent = "Секунду, проверка ещё идёт — отправим сразу после неё.";
      return;
    }
    if (root.dataset.state === "done") expire();
    else hint.textContent = "Отметьте «Я не робот» — без этого форма не отправится.";
    root.dataset.attention = "";
    box.focus();
    box.scrollIntoView({ block: "center", behavior: "smooth" });
  });

  setState("idle", "Я не робот");
})();
