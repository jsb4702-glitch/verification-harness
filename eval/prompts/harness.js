// promptfoo prompt function — DRY: always tests the LIVE harness.
// Loads your real ~/.claude/CLAUDE.md as the system prompt, so eval measures
// whether the harness RULES actually fire the gates (not raw model behavior).
const fs = require('fs');
const path = require('path');

const HARNESS = path.join(process.env.HOME, '.claude', 'CLAUDE.md');

module.exports = async function ({ vars }) {
  let system = '';
  try {
    system = fs.readFileSync(HARNESS, 'utf8');
  } catch (e) {
    system = '(WARN: CLAUDE.md not found at ' + HARNESS + ')';
  }
  return [
    { role: 'system', content: system },
    { role: 'user', content: vars.query },
  ];
};
