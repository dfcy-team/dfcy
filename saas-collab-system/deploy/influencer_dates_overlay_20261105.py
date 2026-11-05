"""Build a hash-fenced narrow patch from a read-only production snapshot."""
import base64
import hashlib
import json
import re
import sys
from pathlib import Path


def sha(data):
    return hashlib.sha256(data).hexdigest()


def once(text, old, new, count=1):
    if text.count(old) != count:
        raise ValueError(f'Unexpected patch anchor count: {old[:90]}')
    return text.replace(old, new)


def build(assets_path, backend_path, output):
    assets = json.loads(Path(assets_path).read_text(encoding='utf-8-sig'))
    backend = json.loads(Path(backend_path).read_text(encoding='utf-8-sig'))
    plan = []

    def add(container, path, before, after):
        plan.append(dict(container=container, path=path,
                         before=sha(before) if before is not None else None,
                         after=sha(after), data=base64.b64encode(after).decode()))

    entry_name = next(n for n in assets if n.startswith('index-'))
    entry = base64.b64decode(assets[entry_name]).decode()
    for name, raw in assets.items():
        if name == entry_name:
            continue
        before = base64.b64decode(raw)
        text = before.decode()
        task = name.startswith('Outreach')
        change, create, message = ('W', 'n', 'k') if task else ('ae', 't', 'h')
        # Reuse this exact component's reactive filter, reset and request object.
        anchor = 'deletedOnly:!1,ordering:"-created_at"}' if task else 'includeDeleted:!1,ordering:"-created_at"}'
        text = once(text, anchor, anchor[:-1] + ',created_from:"",created_to:""}', count=2)
        marker = 'T.deletedOnly&&(l.deleted_only="true");' if task else 'T.includeDeleted&&(l.include_deleted="true");'
        text = once(text, marker, marker + 'T.created_from&&(l.created_from=T.created_from);T.created_to&&(l.created_to=T.created_to);')
        button = 'u(f,{type:"primary",onClick:W}' if task else 'u(m,{type:"primary",onClick:ae}'
        controls = ''
        for field, label in [('created_from', '创建开始日期'), ('created_to', '创建结束日期')]:
            controls += (f'{create}("label",{{style:"display:inline-flex;align-items:center;gap:6px;font-size:12px;white-space:nowrap"}},'
                         f'[{message}("{label}"),{create}("input",{{type:"date","aria-label":"{label}（北京时间）",'
                         f'style:"height:30px;width:142px;border:1px solid #dcdfe6;border-radius:4px;padding:0 6px;color:#303133;background:white",'
                         f'value:T.{field},onChange:a=>{{T.{field}=a.target.value;{change}()}}}})]),')
        text = once(text, button, controls + button)
        digest = sha(text.encode())[:12]
        new_name = name.split('-')[0] + '-dates-' + digest + '.js'
        add('production-frontend-1', '/usr/share/nginx/html/assets/' + new_name, None, text.encode())
        entry = once(entry, name, new_name, count=entry.count(name))
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).with_name(new_name).write_bytes(text.encode())
    add('production-frontend-1', '/usr/share/nginx/html/assets/' + entry_name,
        base64.b64decode(assets[entry_name]), entry.encode())
    before = base64.b64decode(backend['base64'])
    text = before.decode()
    anchor = 'from .product_resolution import resolve_outreach_products\n'
    text = once(text, anchor, anchor + 'from .date_filters import filter_created_dates\n')
    anchor = '        ordering = request.query_params.get("ordering", "-created_at").strip() or "-created_at"'
    text = once(text, anchor, '        queryset = filter_created_dates(queryset, request.query_params)\n' + anchor, count=2)
    compile(text, backend['path'], 'exec')
    add('production-backend-1', backend['path'], before, text.encode())
    helper = Path(__file__).resolve().parents[1] / 'backend/apps/influencers/date_filters.py'
    add('production-backend-1', '/app/apps/influencers/date_filters.py', None, helper.read_bytes())
    Path(output).write_text(json.dumps(plan), encoding='utf-8')
    print(json.dumps([{k: v for k, v in p.items() if k != 'data'} for p in plan], indent=2))


if __name__ == '__main__':
    build(*sys.argv[1:])
