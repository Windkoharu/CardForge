#!/usr/bin/env node
/* Kimi Work / npm preview entry: keep the real Python API, not a static substitute. */
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const python = process.env.CARDFORGE_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
const forwarded = process.argv.slice(2);
const child = spawn(python, ['-m', 'cardforge', 'serve', '--no-browser', ...forwarded], {
  cwd: root,
  stdio: 'inherit',
  env: { ...process.env, PYTHONUNBUFFERED: '1' },
});

let stopping = false;
function stop() {
  if (!stopping && child.exitCode === null && child.signalCode === null) {
    stopping = true;
    child.kill('SIGTERM');
  }
}
process.on('SIGINT', stop);
process.on('SIGTERM', stop);
process.on('exit', stop);
child.on('error', (error) => {
  console.error(`无法启动 Python：${error.message}`);
  console.error('请先运行「启动.bat」完成环境检查，或设置 CARDFORGE_PYTHON。');
  process.exitCode = 1;
});
child.on('exit', (code, signal) => {
  process.exitCode = code ?? (signal ? 1 : 0);
});
