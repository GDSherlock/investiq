import {
  readFileSync,
  readdirSync,
  statSync,
} from 'node:fs';
import { extname, join, relative, resolve } from 'node:path';

const sourceRoot = resolve(process.cwd(), 'src');
const allowedFormatter = 'lib/ui-number-format.ts';
const failures = [];

function sourceFiles(directory) {
  return readdirSync(directory).flatMap((name) => {
    const path = join(directory, name);
    if (statSync(path).isDirectory()) {
      return sourceFiles(path);
    }
    return ['.ts', '.tsx'].includes(extname(path)) &&
      !name.endsWith('.test.ts') &&
      !name.endsWith('.test.tsx') &&
      !name.endsWith('.bak')
      ? [path]
      : [];
  });
}

for (const path of sourceFiles(sourceRoot)) {
  const file = relative(sourceRoot, path);
  const source = readFileSync(path, 'utf8');

  if (file !== allowedFormatter) {
    for (const [label, pattern] of [
      ['toFixed', /\.toFixed\s*\(/g],
      ['toPrecision', /\.toPrecision\s*\(/g],
      ['toLocaleString', /\.toLocaleString\s*\(/g],
      ['Intl.NumberFormat', /new\s+Intl\.NumberFormat\s*\(/g],
    ]) {
      if (pattern.test(source)) {
        failures.push(`${file}: bypasses formatUiNumber with ${label}`);
      }
    }
  }

  for (const tag of source.match(/<YAxis\b[\s\S]*?\/>/g) ?? []) {
    if (!/\btickFormatter\s*=/.test(tag)) {
      failures.push(`${file}: YAxis is missing tickFormatter`);
    }
  }
  for (const tag of source.match(/<Tooltip\b[\s\S]*?\/>/g) ?? []) {
    if (!/\bformatter\s*=/.test(tag)) {
      failures.push(`${file}: Tooltip is missing formatter`);
    }
  }
}

if (failures.length > 0) {
  process.stderr.write(`${failures.join('\n')}\n`);
  process.exitCode = 1;
}
