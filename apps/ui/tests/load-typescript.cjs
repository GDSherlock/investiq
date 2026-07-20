const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

function loadTypeScriptModule(filePath, mocks = {}) {
  const source = fs.readFileSync(filePath, 'utf8');
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      esModuleInterop: true,
      jsx: ts.JsxEmit.ReactJSX,
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
    },
    fileName: filePath,
  });

  const moduleRecord = { exports: {} };
  const localRequire = (specifier) => (
    Object.prototype.hasOwnProperty.call(mocks, specifier)
      ? mocks[specifier]
      : require(specifier)
  );
  const evaluate = new Function(
    'require',
    'module',
    'exports',
    '__filename',
    '__dirname',
    compiled.outputText,
  );

  evaluate(
    localRequire,
    moduleRecord,
    moduleRecord.exports,
    filePath,
    path.dirname(filePath),
  );
  return moduleRecord.exports;
}

module.exports = { loadTypeScriptModule };
