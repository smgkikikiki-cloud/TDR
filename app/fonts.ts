import { Prompt } from "next/font/google";

// Design-system font (design/DESIGN.md §4, tokens v3): Prompt for everything.
// The CSS variable below is wrapped by design/tokens.json as var(--nf-prompt, "Prompt"), so
// --font-display / --font-sans / --font-mono use the self-hosted next/font face and fall back to the plain name.
const prompt = Prompt({ subsets: ["thai", "latin"], weight: ["400", "500", "600", "700"], display: "swap", variable: "--nf-prompt" });

export const designFontVariables = prompt.variable;
