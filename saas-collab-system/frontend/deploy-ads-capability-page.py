"""Publish a versioned page while preserving existing import-map hotfixes."""
import hashlib
import json
import pathlib
import re
import subprocess
root = pathlib.Path('/opt/saas-collab/production/operations/ads-capability-20261110')
container, web = 'production-frontend-1', '/usr/share/nginx/html/'
def run(*args): return subprocess.check_output(args)
def read(name): return run('docker','exec',container,'cat',web+name)
def sha(data): return hashlib.sha256(data).hexdigest()
m = json.loads((root/'manifest.json').read_text())
html = read('index.html')
assert sha(html) == 'cfe688b7fc32a98486dc6103da8a6dc762fb1c5411ba314baa01846cace1b3ae', 'HTML changed'
assert sha(read('assets/'+m['file'])) == m['before'], 'Page changed'
for name, digest in m['dependencies'].items():
    if name == 'index-BCq0YIA9.js':
        assert read('assets/'+name).strip() == b'export * from "./index-v403-32efbbb01679.js";'
        assert read('assets/index-v403-32efbbb01679.js').strip() == b'export * from "./index-v404-665f2bafaee8.js";'
    else:
        assert sha(read('assets/'+name)) == digest, name
assert sha(read('assets/index-v404-665f2bafaee8.js')) == '665f2bafaee86dda2752e8a56ae8fac7cf4537dce50a1afac96bb19f92849dfc'
assert not (root/'index.before.html').exists(), 'Already attempted'
for name,digest in {m['name']:m['after'], **m['additions']}.items():
    assert sha((root/name).read_bytes()) == digest
    run('docker','cp',str(root/name),container+':'+web+'assets/'+name)
    assert sha(read('assets/'+name)) == digest
match = re.search(rb'<script type="importmap">(.*?)</script>',html)
mapping = json.loads(match[1])
mapping['imports']['/assets/'+m['file']] = '/assets/'+m['name']
new = html[:match.start(1)] + json.dumps(mapping,separators=(',',':')).encode() + html[match.end(1):]
(root/'index.before.html').write_bytes(html)
(root/'index.after.html').write_bytes(new)
assert read('index.html') == html
run('docker','cp',str(root/'index.after.html'),container+':'+web+'index.ads.tmp')
run('docker','exec',container,'mv',web+'index.ads.tmp',web+'index.html')
assert read('index.html') == new
print(json.dumps({'page':m['name'],'html_sha256':sha(new)}))
