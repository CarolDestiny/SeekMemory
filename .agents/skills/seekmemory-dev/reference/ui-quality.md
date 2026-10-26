# UI and visible-copy quality

## Design and copy review

- Start with the changed route, state and copy. Match existing dashboard components and visual language; `dashboard/src/ui/styles.css` owns design tokens, so use its tokens instead of scattering literal colors through components.
- Judge styling in context. Gradients, shadows, cards and rounded corners are allowed when they serve the current interface; do not impose blanket style bans or import landing-page rules into this operational dashboard.
- Write for the feature and the user's task. Prefer specific labels, actions and state explanations over vague promotional claims. Treat possible “AI slop” matches as review prompts, not automatic errors.
- When a browser review is available, run the dashboard in Mock mode with `pnpm --dir dashboard dev`; it uses in-memory data and does not write to production. Review the affected route in relevant light/dark themes and viewport sizes. State when visual review could not be performed.

## Scanner status

No scanner is currently included. The candidate scope discussed so far is vague/promotional wording and literal colors that bypass dashboard tokens; matches require human judgment and must not automatically fail CI. Before adding `scripts/scan-ui-quality.py`, settle the phrase list for Chinese and English, supported color syntax, exclusions/false-positive handling, scan scope, and output/exit-code contract. Once implemented, run it for affected UI/copy changes and review every hit; until then, manually review changed UI and visible copy against this guidance.
