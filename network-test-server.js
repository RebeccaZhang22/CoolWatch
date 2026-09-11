const http = require('node:http');

const port = Number(process.env.PORT || 18090);
const server = http.createServer((req, res) => {
  res.writeHead(200, {
    'Content-Type': 'text/plain; charset=utf-8',
    'Cache-Control': 'no-store',
  });
  res.end('OK\n');
});

server.listen(port, '0.0.0.0', () => {
  console.log(`network test server listening on 0.0.0.0:${port}`);
});
