import assert from "node:assert/strict";
import test from "node:test";
import worker from "../dist/server/index.js";

const fetchPath = (path, method = "GET") =>
  worker.fetch(new Request(`https://example.test${path}`, { method }));

test("serves the monitoring dashboard", async () => {
  const response = await fetchPath("/");
  const html = await response.text();

  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type"), /^text\/html/);
  assert.match(html, /TikTok/);
  assert.match(html, /styles\.css/);
  assert.match(html, /app\.js/);
  assert.match(html, /id="productImageUrl"/);
  assert.match(html, /id="productImageFile"/);
  assert.match(html, /东铂跨境/);
  assert.match(html, /id="warehouseRows"/);
  assert.match(html, /id="productCost"/);
});

test("serves application assets and rejects unknown routes", async () => {
  const [script, stylesheet, missing] = await Promise.all([
    fetchPath("/app.js"),
    fetchPath("/styles.css"),
    fetchPath("/missing"),
  ]);

  assert.equal(script.status, 200);
  const scriptText = await script.text();
  assert.match(scriptText, /localStorage/);
  assert.match(scriptText, /compressProductImage/);
  assert.match(scriptText, /image_url/);
  assert.match(scriptText, /inTransit/);
  assert.match(scriptText, /stockMovements/);
  assert.equal(stylesheet.status, 200);
  assert.match(stylesheet.headers.get("content-type"), /^text\/css/);
  assert.equal(missing.status, 404);
});
