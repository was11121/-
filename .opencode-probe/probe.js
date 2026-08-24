// Probe: fetch OpenCode Go usage via local proxy tunnel (127.0.0.1:7890)
const crypto = require('crypto');
const net = require('net');
const tls = require('tls');

const PROXY_HOST = '127.0.0.1';
const PROXY_PORT = 7890;
const API_HOST = 'opencode.ai';
const API_PORT = 443;
const PATH = '/zen/go/v1/usage';
const API_KEY = process.env.OPENCODE_GO_API_KEY || '';

function request() {
  return new Promise((resolve, reject) => {
    const socket = net.connect(PROXY_PORT, PROXY_HOST, () => {
      socket.write(`CONNECT ${API_HOST}:${API_PORT} HTTP/1.1\r\nHost: ${API_HOST}:${API_PORT}\r\n\r\n`);
    });
    let buf = '';
    let tunneled = false;
    socket.on('data', (d) => {
      buf += d.toString('latin1');
      if (!tunneled) {
        const idx = buf.indexOf('\r\n\r\n');
        if (idx < 0) return;
        const head = buf.slice(0, idx);
        if (!/^HTTP\/1\.\d 200/.test(head)) {
          return reject(new Error('TUNNEL_FAIL: ' + head.split('\r\n')[0]));
        }
        tunneled = true;
        const rest = buf.slice(idx + 4);
        buf = '';
        if (rest) socket.emit('data', Buffer.from(rest, 'latin1'));
        startTls();
      }
    });
    function startTls() {
      const tlsSock = tls.connect({ socket, servername: API_HOST }, () => {
        const req = `GET ${PATH} HTTP/1.1\r\nHost: ${API_HOST}\r\nAuthorization: Bearer ${API_KEY}\r\nAccept: application/json\r\nConnection: close\r\n\r\n`;
        tlsSock.write(req);
      });
      let res = '';
      tlsSock.setEncoding('utf8');
      tlsSock.on('data', (chunk) => { res += chunk; });
      tlsSock.on('end', () => resolve(res));
      tlsSock.on('error', reject);
    }
    socket.on('error', reject);
    socket.setTimeout(20000, () => {
      socket.destroy(new Error('TIMEOUT'));
    });
  });
}

request().then((raw) => {
  const idx = raw.indexOf('\r\n\r\n');
  const body = idx >= 0 ? raw.slice(idx + 4) : raw;
  try {
    const parsed = JSON.parse(body);
    console.log(JSON.stringify(parsed));
  } catch (e) {
    console.error('PARSE_FAIL body=' + body.slice(0, 500));
    console.error('HEAD=' + raw.slice(0, idx >= 0 ? idx : 200));
    process.exit(2);
  }
}).catch((e) => {
  console.error('REQ_ERR ' + (e && e.message));
  process.exit(1);
});