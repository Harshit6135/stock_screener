const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { resolve } = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function setup() {
  const nodes = new Map();
  const node = id => {
    if (!nodes.has(id)) nodes.set(id, {
      value: id === "account" ? "first" : "2026-02-04",
      textContent: "", addEventListener() {}, replaceChildren(...rows) { this.rows = rows; },
    });
    return nodes.get(id);
  };
  const requests = new Map(), rendered = [];
  const context = vm.createContext({
    console, Intl, Date, Number, Map, Set,
    document: { getElementById: node, addEventListener() {}, querySelectorAll() { return []; } },
    window: { addEventListener() {} },
    localStorage: { getItem() { return null; } },
    Screener: {
      api(path) { const request = deferred(); requests.set(path, request); return request.promise; },
      row(values) { return values; },
    },
    rendered,
  });
  const source = readFileSync(resolve(__dirname, "../../static/js/portfolio-workspace.js"), "utf8");
  vm.runInContext(source.replace(/\}\)\(\);\s*$/, `
    globalThis.indexMomentumRanking = indexMomentumRanking;
    globalThis.sortRows = sortHoldingRows;
    globalThis.setHoldings = (holdings, ranks, column, direction) => {
      viewData = {holdings}; momentumRanking = indexMomentumRanking(ranks);
      holdingSort = {column, direction};
    };
    const originalSortValue = holdingSortValue;
    globalThis.keyReads = 0;
    holdingSortValue = (...args) => { globalThis.keyReads++; return originalSortValue(...args); };
    render = value => { viewData = value; rendered.push(value.account_id); };
    drawChart = () => {};
    renderHoldings = () => {};
    sortHoldingRows = () => {};
    filterHoldings = () => {};
    stopActions = async () => {};
    globalThis.refresh = refresh;
  })();`), context);
  return { context, requests, rendered, node };
}

test("holdings render while history, journal and rankings are still pending", async () => {
  const { context, requests, rendered } = setup();
  const loading = context.refresh();
  requests.get("/api/portfolio/accounts/first/valuation?as_of_date=2026-02-04")
    .resolve({ account_id: "first", holdings: [] });
  await new Promise(setImmediate);
  assert.deepEqual(rendered, ["first"]);
  requests.get("/api/portfolio/accounts/first/valuation/history?as_of_date=2026-02-04&limit=500")
    .reject(new Error("History unavailable"));
  requests.get("/api/portfolio/accounts/first/journal").reject(new Error("Journal unavailable"));
  requests.get("/api/research/ranking-weeks?strategy_id=momentum").resolve({ week_ends: [] });
  await loading;
  assert.deepEqual(rendered, ["first"]);
  assert.equal(context.document.getElementById("home-error").textContent, "");
  assert.equal(context.document.getElementById("history-note").textContent, "History unavailable");
});

test("responses for an account that is no longer selected do not render", async () => {
  const { context, requests, rendered, node } = setup();
  const loading = context.refresh();
  node("account").value = "second";
  requests.get("/api/portfolio/accounts/first/valuation?as_of_date=2026-02-04")
    .resolve({ account_id: "first", holdings: [] });
  requests.get("/api/portfolio/accounts/first/valuation/history?as_of_date=2026-02-04&limit=500")
    .resolve({ history: [] });
  requests.get("/api/portfolio/accounts/first/journal").resolve({ journal: [] });
  requests.get("/api/research/ranking-weeks?strategy_id=momentum").resolve({ week_ends: [] });
  await loading;
  assert.deepEqual(rendered, []);
});

test("ranking indexes preserve first match and holdings compute one sort key per row", () => {
  const { context, node } = setup();
  const ranks = { week: "2026-02-01", members: [
    { instrument_id: "a", symbol: " AAA ", rank: 2 },
    { instrument_id: "a", symbol: "AAA", rank: 99 },
    { instrument_id: "b", symbol: "BBB", rank: 1 },
  ] };
  const indexed = context.indexMomentumRanking(ranks);
  assert.equal(indexed.byInstrument.get("a").rank, 2);
  assert.equal(indexed.byTrimmedSymbol.get("AAA").rank, 2);
  const holdings = [
    { instrument_id: "a", symbol: "AAA", cost: "10", units: 1 },
    { instrument_id: "b", symbol: "BBB", cost: "10", units: 1 },
    { instrument_id: "c", symbol: "CCC", cost: "10", units: 1 },
  ];
  const rows = holdings.map((_, index) => ({ dataset: { holdingIndex: String(index) } }));
  node("holdings").querySelectorAll = () => rows;
  let sorted;
  node("holdings").append = (...result) => { sorted = result; };
  context.setHoldings(holdings, ranks, 13, "asc");
  context.sortRows();
  assert.deepEqual(sorted.map(row => row.dataset.holdingIndex), ["1", "0", "2"]);
  assert.equal(context.keyReads, rows.length);
});
