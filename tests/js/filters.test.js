// Поиск в списках фильтров сводки: node --test tests/js/filters.test.js
const assert = require("node:assert/strict");
const test = require("node:test");
const { filterOptions, fold, russianDate } = require("../../src/alta_feedback/static/filters.js");

const banks = [
  { value: "", label: "Все банки" },
  { value: "unicredit", label: "UniCredit" },
  { value: "postanska", label: "Poštanska štedionica" },
  { value: "otp", label: "OTP banka" },
];
const cities = [
  { value: "", label: "Все города" },
  { value: "beograd", label: "Белград" },
  { value: "novisad", label: "Нови-Сад" },
  { value: "nis", label: "Ниш" },
];
const labels = (options) => options.map((option) => option.label);

test("подстрока без учёта регистра", () => {
  assert.deepEqual(labels(filterOptions(banks, "uni")), ["UniCredit"]);
});

test("латиница без диакритики находит š", () => {
  assert.deepEqual(labels(filterOptions(banks, "postans")), ["Poštanska štedionica"]);
});

test("đ равно dj", () => {
  assert.equal(fold("Đurđevo"), fold("Djurdjevo"));
});

test("кириллицей находим кириллический город", () => {
  assert.deepEqual(labels(filterOptions(cities, "бел")), ["Белград"]);
});

test("латиницей находим кириллический город", () => {
  assert.deepEqual(labels(filterOptions(cities, "beo")), ["Белград"]);
});

test("ш и š сводятся к одному", () => {
  assert.deepEqual(labels(filterOptions(cities, "niš")), ["Ниш"]);
});

test("пробел вместо дефиса не мешает", () => {
  assert.deepEqual(labels(filterOptions(cities, "нови сад")), ["Нови-Сад"]);
});

test("пустой запрос оставляет все варианты, включая «все»", () => {
  assert.equal(filterOptions(banks, "  ").length, banks.length);
});

test("пункт «все» не попадает в результаты поиска", () => {
  assert.deepEqual(labels(filterOptions(banks, "все")), []);
});

test("дата показывается по-русски", () => {
  assert.equal(russianDate("2026-10-12"), "12.10.2026");
});

test("пустая дата — пустая строка", () => {
  assert.equal(russianDate(""), "");
});
