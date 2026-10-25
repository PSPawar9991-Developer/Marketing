"""Local prospecting dashboard. Python 3.12+, no third-party dependencies."""
import csv
import http.client
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import ssl
import threading
from email.message import EmailMessage
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, urljoin, urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parent
DB = ROOT / '.data' / 'prospects.sqlite3'
LOCK = threading.Lock()
STATUSES = {'New', 'Reviewed', 'Contacted', 'Replied', 'Won', 'Closed'}
FIELDS = {'name', 'website', 'email', 'region', 'category', 'notes', 'status', 'linkedin', 'instagram', 'do_not_contact', 'subject', 'message'}

def connect():
    DB.parent.mkdir(exist_ok=True)
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    return db

def init():
    with connect() as db:
        db.executescript('''CREATE TABLE IF NOT EXISTS prospects (
          id INTEGER PRIMARY KEY, name TEXT NOT NULL, website TEXT DEFAULT '',
          email TEXT DEFAULT '', region TEXT DEFAULT '', category TEXT DEFAULT '',
          source TEXT DEFAULT 'Manual', source_url TEXT DEFAULT '', external_id TEXT UNIQUE,
          notes TEXT DEFAULT '', status TEXT DEFAULT 'New', linkedin TEXT DEFAULT '',
          instagram TEXT DEFAULT '', do_not_contact INTEGER DEFAULT 0,
          findings TEXT DEFAULT '[]', subject TEXT DEFAULT '', message TEXT DEFAULT '',
          created_at TEXT DEFAULT CURRENT_TIMESTAMP);
          CREATE TABLE IF NOT EXISTS activity (id INTEGER PRIMARY KEY, prospect_id INTEGER,
          kind TEXT, detail TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
          CREATE TABLE IF NOT EXISTS sends (prospect_id INTEGER, message_id TEXT,
          state TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(prospect_id));''')

def all_prospects():
    with connect() as db:
        return [dict(row) for row in db.execute('SELECT * FROM prospects ORDER BY id DESC')]

def get(pid):
    with connect() as db:
        row = db.execute('SELECT * FROM prospects WHERE id=?', (pid,)).fetchone()
    if not row:
        raise ValueError('Prospect not found')
    return dict(row)

def add(data):
    name = str(data.get('name', '')).strip()
    if not name:
        raise ValueError('Business name is required')
    keys = ['name', 'website', 'email', 'region', 'category', 'source', 'source_url', 'external_id']
    values = [name] + [str(data.get(k, '')).strip() for k in keys[1:]]
    values[-1] = values[-1] or None
    with connect() as db:
        if values[-1] and db.execute('SELECT id FROM prospects WHERE external_id=?', (values[-1],)).fetchone():
            return False
        if values[1] and db.execute('SELECT id FROM prospects WHERE lower(website)=lower(?)', (values[1],)).fetchone():
            return False
        db.execute(f'INSERT INTO prospects ({",".join(keys)}) VALUES ({",".join("?" for _ in keys)})', values)
    return True

def update(pid, data):
    get(pid)
    changes = {k: str(v).strip() for k, v in data.items() if k in FIELDS}
    if 'status' in changes and changes['status'] not in STATUSES:
        raise ValueError('Invalid status')
    if 'name' in changes and not changes['name']:
        raise ValueError('Name cannot be empty')
    if 'do_not_contact' in changes:
        changes['do_not_contact'] = int(str(changes['do_not_contact']).lower() in {'true', '1'})
    if changes:
        with connect() as db:
            db.execute('UPDATE prospects SET ' + ','.join(f'{k}=?' for k in changes) + ' WHERE id=?', [*changes.values(), pid])

def api_request(url, data=None, headers=None, form=False):
    headers = dict(headers or {})
    body = None
    if data is not None:
        body = (urlencode(data) if form else json.dumps(data)).encode()
        headers['Content-Type'] = 'application/x-www-form-urlencoded' if form else 'application/json'
    try:
        with urlopen(Request(url, data=body, headers=headers), timeout=25) as response:
            return json.load(response)
    except HTTPError as e:
        # Do not echo provider response bodies: they can contain credentials or personal data.
        raise ValueError(f'Provider returned HTTP {e.code}; check credentials, API activation, quota and permissions.') from None

def search(data):
    provider = data.get('provider')
    region = data.get('region')
    term = str(data.get('term', '')).strip()
    city = str(data.get('city', '')).strip()
    if region not in {'Australia', 'United Kingdom'} or not term or not city:
        raise ValueError('Choose Australia or United Kingdom, and enter a city and industry')
    items = []
    if provider == 'google':
        key = os.getenv('GOOGLE_PLACES_API_KEY')
        if not key:
            raise ValueError('Set GOOGLE_PLACES_API_KEY to use Google Places search')
        result = api_request('https://places.googleapis.com/v1/places:searchText', {
            'textQuery': f'{term} in {city}, {region}', 'pageSize': 20,
            'regionCode': 'AU' if region == 'Australia' else 'GB'}, {
            'X-Goog-Api-Key': key,
            'X-Goog-FieldMask': 'places.id,places.displayName,places.websiteUri,places.googleMapsUri,places.formattedAddress'})
        for p in result.get('places', []):
            items.append(dict(name=p.get('displayName', {}).get('text', ''), website=p.get('websiteUri', ''),
                source='Google Places', source_url=p.get('googleMapsUri', ''), external_id='google:' + p['id']))
    elif provider == 'yelp':
        key = os.getenv('YELP_API_KEY')
        if not key:
            raise ValueError('Set YELP_API_KEY to use Yelp search')
        result = api_request('https://api.yelp.com/v3/businesses/search?' + urlencode({
            'term': term, 'location': f'{city}, {region}', 'limit': 20}), headers={'Authorization': 'Bearer ' + key})
        for p in result.get('businesses', []):
            # Yelp's url points to a listing, not the business website.
            items.append(dict(name=p['name'], source='Yelp', source_url=p.get('url', ''), external_id='yelp:' + p['id']))
    else:
        raise ValueError('Unknown search provider')
    for p in items:
        p.update(region=region, category=term)
    return items

class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, hostname, ip):
        super().__init__(hostname, timeout=12, context=ssl.create_default_context())
        self.ip = ip
    def connect(self):
        sock = socket.create_connection((self.ip, 443), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)

def fetch_public(url, redirects=0):
    """Fetch a public website with verified TLS, pinned public IP, and bounded output."""
    if redirects > 4:
        raise ValueError('Too many website redirects')
    parsed = urlsplit(url)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Enter a public HTTP or HTTPS website URL')
    port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    if port != (443 if parsed.scheme == 'https' else 80):
        raise ValueError('Website checks support standard HTTP/HTTPS ports only')
    addresses = list(dict.fromkeys(x[4][0] for x in socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)))
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise ValueError('Website must resolve only to public Internet addresses')
    ip = addresses[0]
    conn = PinnedHTTPS(parsed.hostname, ip) if parsed.scheme == 'https' else http.client.HTTPConnection(ip, 80, timeout=12)
    try:
        conn.request('GET', (parsed.path or '/') + ('?' + parsed.query if parsed.query else ''), headers={
            'Host': parsed.hostname, 'User-Agent': 'MarketingWebsiteReview/1.0', 'Accept': 'text/html'})
        response = conn.getresponse()
        if response.status in {301, 302, 303, 307, 308}:
            location = response.getheader('Location')
            if not location:
                raise ValueError('Website redirect has no destination')
            return fetch_public(urljoin(url, location), redirects + 1)
        if response.status != 200:
            raise ValueError(f'Website returned HTTP {response.status}')
        if 'text/html' not in response.getheader('Content-Type', '').lower():
            raise ValueError('Website did not return an HTML page')
        raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError('Page is too large for this basic check')
        return url, raw.decode('utf-8', errors='replace')
    finally:
        conn.close()

def analyze(pid):
    p = get(pid)
    final, html = fetch_public(p['website'])
    findings = []
    if urlsplit(final).scheme != 'https':
        findings.append('The checked homepage was served over HTTP rather than HTTPS.')
    if not re.search(r'<title\b[^>]*>\s*[^<\s]', html, re.I):
        findings.append('The homepage HTML has no non-empty title element.')
    if not re.search(r'<meta\b[^>]*name\s*=\s*[\'\"]description[\'\"]', html, re.I):
        findings.append('The homepage HTML has no meta description tag.')
    if not re.search(r'<meta\b[^>]*name\s*=\s*[\'\"]viewport[\'\"]', html, re.I):
        findings.append('The homepage HTML has no viewport meta tag.')
    if not re.search(r'<h1\b', html, re.I):
        findings.append('The homepage HTML has no H1 element.')
    with connect() as db:
        db.execute('UPDATE prospects SET findings=? WHERE id=?', (json.dumps(findings), pid))
        db.execute('INSERT INTO activity(prospect_id,kind,detail) VALUES(?,?,?)', (pid, 'Website check', json.dumps({'url': final, 'findings': findings, 'scope': 'Homepage HTML only; no rendered-browser, speed, ranking or accessibility audit.'})))
    return {'findings': findings, 'checked_url': final, 'scope': 'Homepage HTML only. JavaScript-rendered content may differ; manually verify findings before outreach.'}

def draft(pid):
    p = get(pid)
    findings = json.loads(p['findings'])
    observation = ('While checking your homepage HTML, I noticed: ' + findings[0] + ' ') if findings else ''
    message = (f'Hi {p["name"]} team,\n\nI came across your business while researching {p["category"] or "local"} businesses in {p["region"] or "your area"}. '
        + observation + '\n\nI’m Prasad, a freelance WordPress developer. I help businesses with website improvements, maintenance and on-page SEO. '
        + 'Would you be interested in two or three suggestions for your website?\n\nThanks,\nPrasad\n\nIf this is not relevant, let me know and I won’t contact you again.')
    update(pid, {'subject': f'A website idea for {p["name"]}', 'message': message})
    return get(pid)

def send(pid, data):
    p = get(pid)
    if p['do_not_contact']:
        raise ValueError('This prospect is marked do not contact')
    if data.get('confirm') is not True:
        raise ValueError('Explicit send confirmation is required')
    if p['status'] != 'Reviewed':
        raise ValueError('Review the prospect and mark it Reviewed before sending')
    if not re.fullmatch(r'[^\s@<>\r\n]+@[^\s@<>\r\n]+\.[^\s@<>\r\n]+', p['email']):
        raise ValueError('Add a valid, verified recipient email address')
    names = ['GMAIL_CLIENT_ID', 'GMAIL_CLIENT_SECRET', 'GMAIL_REFRESH_TOKEN', 'GMAIL_SENDER']
    if any(not os.getenv(k) for k in names):
        raise ValueError('Gmail OAuth configuration is incomplete')
    if not p['subject'] or not p['message']:
        raise ValueError('Prepare the subject and message first')
    msg = EmailMessage()
    msg['From'] = os.environ['GMAIL_SENDER']
    msg['To'] = p['email']
    msg['Subject'] = p['subject']
    msg.set_content(p['message'])
    # Claim once before network I/O. An ambiguous send is never retried automatically.
    with LOCK, connect() as db:
        if db.execute('SELECT 1 FROM sends WHERE prospect_id=?', (pid,)).fetchone():
            raise ValueError('This prospect already has a send attempt. Check Gmail Sent before any further outreach.')
        db.execute('INSERT INTO sends(prospect_id,state) VALUES(?,?)', (pid, 'Pending'))
    try:
        token = api_request('https://oauth2.googleapis.com/token', {
            'client_id': os.environ['GMAIL_CLIENT_ID'], 'client_secret': os.environ['GMAIL_CLIENT_SECRET'],
            'refresh_token': os.environ['GMAIL_REFRESH_TOKEN'], 'grant_type': 'refresh_token'}, form=True)
        sent = api_request('https://gmail.googleapis.com/gmail/v1/users/me/messages/send',
            {'raw': base64.urlsafe_b64encode(msg.as_bytes()).decode()}, {'Authorization': 'Bearer ' + token['access_token']})
        with connect() as db:
            db.execute('UPDATE sends SET state=?, message_id=? WHERE prospect_id=?', ('Sent', sent['id'], pid))
            db.execute("UPDATE prospects SET status='Contacted' WHERE id=?", (pid,))
            db.execute('INSERT INTO activity(prospect_id,kind,detail) VALUES(?,?,?)', (pid, 'Email sent', sent['id']))
        return {'sent': True}
    except Exception:
        with connect() as db:
            db.execute('UPDATE sends SET state=? WHERE prospect_id=?', ('Needs manual verification', pid))
        raise ValueError('Send did not complete cleanly. Check Gmail Sent; this app will not retry automatically.') from None

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass
    def reply(self, value, status=200):
        raw = json.dumps(value).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(raw)
    def valid_host(self):
        return self.headers.get('Host', '') in {
            f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
    def do_GET(self):
        if not self.valid_host():
            return self.reply({'error': 'Untrusted Host header'}, 403)
        if self.path == '/api/config':
            return self.reply({'google': bool(os.getenv('GOOGLE_PLACES_API_KEY')), 'yelp': bool(os.getenv('YELP_API_KEY')),
                'gmail': all(os.getenv(k) for k in ['GMAIL_CLIENT_ID','GMAIL_CLIENT_SECRET','GMAIL_REFRESH_TOKEN','GMAIL_SENDER'])})
        if self.path == '/api/prospects':
            return self.reply(all_prospects())
        if self.path.startswith('/api/activity/'):
            try:
                pid = int(self.path.rsplit('/', 1)[1])
                with connect() as db:
                    rows = [dict(r) for r in db.execute('SELECT * FROM activity WHERE prospect_id=? ORDER BY id DESC', (pid,))]
                return self.reply(rows)
            except ValueError:
                return self.reply({'error': 'Invalid prospect id'}, 400)
        paths = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'), '/style.css': ('style.css', 'text/css')}
        if self.path not in paths:
            return self.reply({'error': 'Not found'}, 404)
        name, mime = paths[self.path]
        raw = (ROOT / 'static' / name).read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', mime + '; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(raw)
    def do_POST(self):
        if not self.valid_host():
            return self.reply({'error': 'Untrusted Host header'}, 403)
        # No cross-origin requests or HTML forms can mutate this local app.
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            return self.reply({'error': 'JSON required'}, 415)
        origin = self.headers.get('Origin')
        if origin and origin != 'http://' + self.headers.get('Host', ''):
            return self.reply({'error': 'Cross-origin request blocked'}, 403)
        try:
            size = int(self.headers.get('Content-Length', 0))
            if size < 1 or size > 1_000_000:
                raise ValueError('Request size must be between 1 and 1000000 bytes')
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ValueError('JSON object required')
            if self.path == '/api/search':
                return self.reply({'results': search(data)})
            if self.path == '/api/import':
                rows = list(csv.DictReader(io.StringIO(str(data.get('csv', '')))))
                if len(rows) > 500:
                    raise ValueError('Import at most 500 rows at a time')
                if any(not r.get('name', '').strip() for r in rows):
                    raise ValueError('Every CSV row requires a name column')
                return self.reply({'added': sum(add(r) for r in rows)})
            if self.path == '/api/prospects':
                return self.reply({'added': add(data)})
            match = re.fullmatch(r'/api/prospects/(\d+)/(update|analyze|draft|send)', self.path)
            if not match:
                return self.reply({'error': 'Not found'}, 404)
            pid, action = int(match[1]), match[2]
            if action == 'update':
                update(pid, data)
                return self.reply(get(pid))
            if action == 'analyze':
                return self.reply(analyze(pid))
            if action == 'draft':
                return self.reply(draft(pid))
            return self.reply(send(pid, data))
        except (ValueError, OSError, http.client.HTTPException) as e:
            return self.reply({'error': str(e)}, 400)
        except Exception:
            return self.reply({'error': 'Operation failed. Check configuration and try again.'}, 500)

if __name__ == '__main__':
    init()
    server = ThreadingHTTPServer(('127.0.0.1', int(os.getenv('PORT', '8000'))), Handler)
    print(f'Marketing dashboard listening on port {server.server_port}', flush=True)
    server.serve_forever()
