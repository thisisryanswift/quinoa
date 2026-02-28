---
name: ux-design
description: Design and UX resource for auditing screenshots and evaluating UI for aesthetic "taste," usability heuristics, and information hierarchy. Use when you need a critique of a UI screenshot or guidance on making an interface feel more modern and polished.
---

# UX/Design Resource

This skill provides expert design reviews for interfaces, focusing on modern desktop aesthetics and usability standards. It's built to "parse" screenshots and provide structured, actionable design advice.

## Core Workflows

### 1. The Screenshot Audit

When presented with a screenshot of the app's UI, follow this multi-step audit:

1.  **Visual First Impression:** Does the app look like a "utility" or a "product"? (Check: Contrast, Colors, Spacing).
2.  **Information Architecture:** Is the primary call to action (CTA) obvious? Is the reading order clear (Top-Left to Bottom-Right)?
3.  **Heuristic Check:** Compare the UI against the 10 Usability Heuristics. Look for missing feedback, inconsistent icons, or poor error prevention.
4.  **Polish & Taste:** Look for "micro-design" improvements (e.g., "Add 4px of rounding here," "Change this border to a soft shadow").

See [heuristics.md](references/heuristics.md) for the specific principles used in this audit.

### 2. Information Hierarchy Optimization

Use this workflow when the user reports a screen feels "cluttered" or "confusing."

1.  **Map Element Priority:** Identify the top 3 most important elements on the screen.
2.  **Simplify:** Group related items together with subtle backgrounds or whitespace.
3.  **De-emphasize:** Make secondary or tertiary information smaller or lower-contrast (e.g., using a lighter gray).
4.  **Enforce Whitespace:** Suggest minimum "padding" rules to create breathing room.

## Design Patterns to Recommend

- **Empty States:** Suggest a friendly graphic or helpful text when no data is available (instead of a blank screen).
- **Progressive Disclosure:** Hide advanced settings behind a "More" menu or an "Advanced" toggle to keep the main UI clean.
- **Skeletons over Spinners:** Suggest "skeleton loaders" (ghost UI shapes) instead of a simple loading spinner for a smoother perceived speed.

## Quick References

- **Aesthetic Principles & Usability:** See `references/heuristics.md`
