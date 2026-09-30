import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { test } from "node:test";
import {
  applyTheme,
  currentTheme,
  THEME_STORAGE_KEY,
} from "../src/utils/theme.js";

const bootstrap = readFileSync(
  new URL("../public/theme.js", import.meta.url),
  "utf8",
);

function environment(saved, blocked = false) {
  const values = new Map(saved ? [[THEME_STORAGE_KEY, saved]] : []);
  const meta = {};
  return {
    document: {
      documentElement: { dataset: {} },
      querySelector: () => ({
        setAttribute: (name, value) => {
          meta[name] = value;
        },
      }),
    },
    localStorage: {
      getItem(key) {
        if (blocked) throw new Error("Storage unavailable");
        return values.get(key) ?? null;
      },
      setItem(key, value) {
        if (blocked) throw new Error("Storage unavailable");
        values.set(key, value);
      },
    },
    values,
    meta,
  };
}

for (const [saved, expected] of [
  [null, "dark"],
  ["light", "light"],
  ["dark", "dark"],
  ["invalid", "dark"],
]) {
  test(`bootstrap: ${saved ?? "no preference"} → ${expected}`, () => {
    const env = environment(saved);
    runInNewContext(bootstrap, env);
    assert.equal(env.document.documentElement.dataset.theme, expected);
    assert.equal(env.meta.content, expected === "dark" ? "#101b26" : "#f4f6f8");
  });
}

test("bootstrap survives blocked storage", () => {
  const env = environment(null, true);
  runInNewContext(bootstrap, env);
  assert.equal(env.document.documentElement.dataset.theme, "dark");
});

for (const blocked of [false, true]) {
  test(`switch both directions, storage blocked=${blocked}`, (t) => {
    const env = environment(null, blocked);
    const originalDocument = Object.getOwnPropertyDescriptor(
      globalThis,
      "document",
    );
    const originalStorage = Object.getOwnPropertyDescriptor(
      globalThis,
      "localStorage",
    );
    Object.defineProperty(globalThis, "document", {
      configurable: true,
      value: env.document,
    });
    Object.defineProperty(globalThis, "localStorage", {
      configurable: true,
      value: env.localStorage,
    });
    t.after(() => {
      for (const [key, descriptor] of [
        ["document", originalDocument],
        ["localStorage", originalStorage],
      ]) {
        if (descriptor) Object.defineProperty(globalThis, key, descriptor);
        else delete globalThis[key];
      }
    });
    assert.equal(currentTheme(), "dark");
    assert.equal(applyTheme("light"), "light");
    assert.equal(currentTheme(), "light");
    if (!blocked) {
      const reloaded = environment(env.values.get(THEME_STORAGE_KEY));
      runInNewContext(bootstrap, reloaded);
      assert.equal(reloaded.document.documentElement.dataset.theme, "light");
    }
    assert.equal(applyTheme("dark"), "dark");
    assert.equal(currentTheme(), "dark");
    if (!blocked) assert.equal(env.values.get(THEME_STORAGE_KEY), "dark");
  });
}
