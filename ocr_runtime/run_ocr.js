const { processOcrRequest } = require('./handler-ocr');

console.log = (...args) => console.error(...args);

function readStdin() {
  return new Promise((resolve, reject) => {
    let body = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', chunk => { body += chunk; });
    process.stdin.on('error', reject);
    process.stdin.on('end', () => resolve(body));
  });
}

async function main() {
  const body = await readStdin();
  const payload = JSON.parse(body || '{}');
  const response = await processOcrRequest(payload);
  process.stdout.write(JSON.stringify(response.body));
}

main().catch(error => {
  const message = error && error.message ? error.message : String(error);
  process.stderr.write(`${message}\n`);
  process.stdout.write(JSON.stringify({ status: 500, message: 'failed', error: message }));
  process.exitCode = 1;
});
