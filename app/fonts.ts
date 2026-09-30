import { Anuphan, IBM_Plex_Sans_Thai, IBM_Plex_Mono } from "next/font/google";

// Design-system fonts (design/DESIGN.md §4). Each font exposes a CSS variable that
// design/tokens.json wraps as var(--nf-…, "Font Name"), so --font-display / --font-sans /
// --font-mono use the self-hosted next/font face and fall back to the plain name.
// The legacy Prompt @import in globals.css is untouched until pages migrate.
const anuphan = Anuphan({ subsets: ["thai", "latin"], weight: "variable", display: "swap", variable: "--nf-anuphan" });
const plexThai = IBM_Plex_Sans_Thai({ subsets: ["thai", "latin"], weight: ["400", "500", "600", "700"], display: "swap", variable: "--nf-plex-thai" });
const plexMono = IBM_Plex_Mono({ subsets: ["latin"], weight: ["400", "500", "600"], display: "swap", variable: "--nf-plex-mono" });

export const designFontVariables = [anuphan.variable, plexThai.variable, plexMono.variable].join(" ");
