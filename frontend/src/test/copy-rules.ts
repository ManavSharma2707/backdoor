/** The copy rules from ui-copywriting.md, as functions the tests can share. */

const LONG_DASHES = new RegExp(`[${String.fromCharCode(0x2014)}${String.fromCharCode(0x2013)}]`);

export const BANNED = [
  "seamless",
  "seamlessly",
  "robust",
  "powerful",
  "leverage",
  "utilise",
  "unlock",
  "supercharge",
  "elevate",
  "empower",
  "effortless",
  "effortlessly",
  "streamline",
  "cutting-edge",
  "state-of-the-art",
  "game-changer",
  "revolutionary",
  "intelligent",
  "smart",
  "ai-powered",
  "magic",
  "magical",
  "delve",
  "dive in",
  "journey",
  "ecosystem",
  "holistic",
  "synergy",
  "at your fingertips",
  "in today's",
  "it's important to note",
  "welcome back",
  "let's get started",
  "oops",
  "uh oh",
  "hang tight",
  "sit back and relax",
  "simply",
  "just",
  "easily",
  "insights",
  "actionable",
  "best-in-class",
  "next-level",
];

const EMOJI = /\p{Extended_Pictographic}/u;

/** What is wrong with this text, as a list of plain findings. Empty means it is fine. */
export function copyProblems(text: string): string[] {
  const found: string[] = [];
  if (LONG_DASHES.test(text)) found.push("long dash");
  if (text.includes("!")) found.push("exclamation mark");
  if (EMOJI.test(text)) found.push("emoji");
  const lower = text.toLowerCase();
  for (const word of BANNED) {
    if (
      new RegExp(`(?<![\\w-])${word.replace(/[-/\\^$*+?.()|[\]{}]/g, "\\$&")}(?![\\w-])`).test(
        lower,
      )
    ) {
      found.push(`banned word "${word}"`);
    }
  }
  return found;
}

/** Visible text plus the text a screen reader or tooltip would read. */
export function pageText(root: HTMLElement = document.body): string {
  const parts = [root.textContent ?? ""];
  root.querySelectorAll("[aria-label],[placeholder],[title]").forEach((el) => {
    for (const attr of ["aria-label", "placeholder", "title"]) {
      const value = el.getAttribute(attr);
      if (value) parts.push(value);
    }
  });
  return parts.join("\n");
}
