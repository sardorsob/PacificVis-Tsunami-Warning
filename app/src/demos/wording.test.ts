import { readdirSync, readFileSync } from "node:fs";
import { parseSync } from "vite";
import { describe, expect, it } from "vitest";

/**
 * The wording gate (context STORYBOARD "Copy sweep v2", gate check for T-SV-04). Every reader-visible string in the demo source must never
 * say "warning time", and says "arrival" or "arrivals" only in "validated arrival time(s)".
 *
 * Reader-visible strings are string literals, template-literal text and JSX text; comments are never read. The source is parsed with the oxc
 * parser vite already ships (`parseSync`), so no dependency is added. An "arrival" is not reader-visible when it is part of
 * - a code identifier: the whole string is a lower-case identifier ("arrivals", "arrival_comparison_allowed"), or the word is joined to an
 *   identifier character (reported_arrival_display_allowed, StoryArrivals);
 * - a file or path name: joined to "/", "-" or "." ("./arrivals", "story-arrivals-v2/x.json", "arrival-evidence");
 * - a URL value: right after "=" ("view=arrivals").
 * Anything else needs an exact entry in ALLOWED, with its reason.
 */
const ALLOWED: Record<string, string> = {
  "unsafe arrivals reference": "the events-index validator's error names the index field `arrivals`",
};
const IDENTIFIER = /^[a-z_$][\w$]*$/;

type Found = { line: number; text: string };
/** The reader-visible strings of one source file that break the gate. */
export function findings(file: string, source: string): Found[] {
  const parsed = parseSync(file, source);
  if (parsed.errors.length) throw new Error(`${file}: ${parsed.errors[0].message}`);
  const out: Found[] = [], line = (at: number) => source.slice(0, at).split("\n").length;
  const check = (text: string, at: number) => {
    if (ALLOWED[text] !== undefined || IDENTIFIER.test(text)) return;
    const s = text.replace(/validated arrival times?/gi, "");
    const bad = /warning time/i.test(s) || [...s.matchAll(/arrivals?/gi)].some(m => {
      const before = s[m.index - 1] ?? "", after = s[m.index + m[0].length] ?? "", next = s[m.index + m[0].length + 1] ?? "";
      return !(/[\w$/.=-]/.test(before) || /[\w$/-]/.test(after) || (after === "." && /\w/.test(next)));
    });
    if (bad) out.push({ line: line(at), text: text.trim() });
  };
  const walk = (node: unknown): void => {
    if (Array.isArray(node)) { node.forEach(walk); return; }
    if (!node || typeof node !== "object") return;
    const n = node as { type?: string; value?: unknown; start?: number };
    if ((n.type === "Literal" || n.type === "JSXText") && typeof n.value === "string") check(n.value, n.start ?? 0);
    else if (n.type === "TemplateElement") { const v = n.value as { cooked: string | null; raw: string }; check(v.cooked ?? v.raw, n.start ?? 0); }
    for (const v of Object.values(node)) if (v && typeof v === "object") walk(v);
  };
  walk(parsed.program);
  return out;
}

const root = new URL("./", import.meta.url);
/** Non-test source: every .ts and .tsx file except tests, real-data integration tests and their reader. */
const sources = (readdirSync(root, { recursive: true }) as string[])
  .filter(f => /\.tsx?$/.test(f) && !/\.(test|integration)\.tsx?$/.test(f) && !f.endsWith("integration-data.ts")).sort();

describe("the wording gate", () => {
  it("finds a bad string and passes the exceptions the gate names", () => {
    const planted = `// a comment may say arrival or warning time
      const keys = ["arrivals", "arrival_comparison_allowed"], path = "story-arrivals-v2/x.json", url = "?view=arrivals", d = "arrival-evidence/a.csv";
      import { linkedReports } from "./arrivals";
      export const A = () => <p title="not validated arrival times">Reported times are not validated arrivals.</p>;
      export const B = \`first arrival only\`, C = "not warning time", D = "Arrivals", E = "unsafe arrivals reference";`;
    expect(findings("planted.tsx", planted).map(f => f.text)).toEqual(["Reported times are not validated arrivals.", "first arrival only", "not warning time", "Arrivals"]);
  });
  it("reads the demo source", () => {
    expect(sources).toContain("DemoApp.tsx");
    expect(sources).toContain("story/StoryView.tsx");
    expect(sources.some(f => f.includes(".test."))).toBe(false);
  });
  it("finds no reader-visible “warning time” and no “arrival” outside “validated arrival time(s)” in the demo source", () => {
    const bad = sources.flatMap(f => findings(f, readFileSync(new URL(f, root), "utf8")).map(x => `${f}:${x.line}: ${x.text}`));
    expect(bad).toEqual([]);
  });
});
