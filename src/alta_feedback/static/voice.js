// Голосовой ввод в комментарий через распознавание речи браузера (без нашего сервера).
// Нет SpeechRecognition — кнопка остаётся скрытой, остаётся микрофон клавиатуры телефона.
(() => {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const button = document.getElementById("mic");
  const label = document.getElementById("mic-label");
  const status = document.getElementById("mic-status");
  const box = document.getElementById("comment");
  if (!Recognition || !button || !box) return;

  const limit = Number(box.getAttribute("maxlength")) || 1000;
  let recognition = null;
  let before = "";

  const setListening = (on) => {
    button.classList.toggle("on", on);
    label.textContent = on ? "Стоп" : "Голосом";
  };

  const errorText = (code) => {
    if (code === "not-allowed" || code === "service-not-allowed") return "Нет доступа к микрофону — разрешите его в браузере.";
    if (code === "no-speech") return "Ничего не услышали, попробуйте ещё раз.";
    if (code === "network") return "Распознавание недоступно без интернета.";
    return "Не получилось распознать, можно напечатать.";
  };

  const start = () => {
    recognition = new Recognition();
    recognition.lang = "ru-RU";
    recognition.interimResults = true;
    recognition.continuous = true;
    before = box.value.trim();
    recognition.onresult = (event) => {
      let heard = "";
      for (let i = 0; i < event.results.length; i += 1) heard += event.results[i][0].transcript;
      box.value = ((before ? before + " " : "") + heard.trim()).slice(0, limit);
    };
    recognition.onerror = (event) => { status.textContent = errorText(event.error); };
    recognition.onend = () => { recognition = null; setListening(false); };
    status.textContent = "";
    recognition.start();
    setListening(true);
  };

  button.hidden = false;
  const note = document.getElementById("mic-note");
  if (note) note.hidden = false;
  button.addEventListener("click", () => {
    if (recognition) recognition.stop();
    else start();
  });
})();
