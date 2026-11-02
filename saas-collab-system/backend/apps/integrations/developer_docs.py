"""Credential-free local development handoff generated from effective grants."""
import io
import json
import zipfile
from datetime import datetime, timedelta, timezone
from django.http import HttpResponse
from .models import DeveloperEndpoint


def documentation_response(app, request):
    endpoints = list(DeveloperEndpoint.objects.filter(config__tenant_id=app.tenant_id, approved=True, id__in=app.approved_endpoint_ids))
    base = request.build_absolute_uri('/').rstrip('/')
    paths = {}
    items = []
    # Use a fresh, bounded Unix-time window so the downloaded request remains
    # usable without advertising parameters for endpoints that were not granted.
    now = datetime.now(timezone.utc)
    shopee_order_query = {
        'time_range_field': 'create_time',
        'time_from': int((now - timedelta(days=1)).timestamp()),
        'time_to': int(now.timestamp()),
        'page_size': 50,
        'response_optional_fields': 'order_status',
    }
    shopee_product_query = {'offset': 0, 'page_size': 50, 'item_status': ['NORMAL']}
    for endpoint in endpoints:
        path = f'/api/developer-gateway/v1/{app.pk}/{endpoint.code}/'
        paths[path] = {'post': {'summary': endpoint.name, 'security': [{'bearerAuth': []}], 'requestBody': {'content': {'application/json': {'schema': {'type':'object','properties':{'query':{'type':'object'},'body':{'type':'object'}}}}}}, 'responses': {'200': {'description':'Provider result and request_id'}, '401': {'description':'Expired or revoked token'}, '403': {'description':'Endpoint not granted'}, '429': {'description':'Rate limit'}}}}
        query = {}
        if endpoint.auth_mode == 'shopee_shop' and endpoint.relative_path == '/api/v2/order/get_order_list':
            query = shopee_order_query
        elif endpoint.auth_mode == 'shopee_shop' and endpoint.relative_path == '/api/v2/product/get_item_list':
            query = shopee_product_query
        items.append({'name':endpoint.name,'request':{'method':'POST','header':[{'key':'Content-Type','value':'application/json'}], 'url': '{{base_url}}' + path, 'body':{'mode':'raw','raw':json.dumps({'query': query}, ensure_ascii=False)}}})
    document = {'openapi':'3.1.0','info':{'title':app.name,'version':'1.0.0'},'servers':[{'url':base}], 'components':{'securitySchemes':{'bearerAuth':{'type':'http','scheme':'bearer'}}}, 'paths':paths}
    first = endpoints[0].code if endpoints else 'ENDPOINT_CODE'
    gateway = f'/api/developer-gateway/v1/{app.pk}/{first}/'
    files = {
        'openapi.json': json.dumps(document, ensure_ascii=False, indent=2),
        'postman.json': json.dumps({'info':{'name':app.name,'schema':'https://schema.getpostman.com/json/collection/v2.1.0/collection.json'}, 'auth':{'type':'bearer','bearer':[{'key':'token','value':'{{developer_token}}','type':'string'}]}, 'variable':[{'key':'base_url','value':base},{'key':'developer_token','value':''}], 'item':items}, ensure_ascii=False, indent=2),
        '.env.example': f'DEVELOPER_API_URL={base}\nDEVELOPER_TOKEN=\nDEVELOPER_ENDPOINT={gateway}\n',
        'example.py': '''import json, os, urllib.request, urllib.error
url = os.environ['DEVELOPER_API_URL'].rstrip('/') + os.environ['DEVELOPER_ENDPOINT']
payload = {'query': {}}  # Fill provider-specific query/pagination parameters.
request = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={'Authorization': 'Bearer ' + os.environ['DEVELOPER_TOKEN'], 'Content-Type': 'application/json'}, method='POST')
try:
    with urllib.request.urlopen(request, timeout=20) as response:
        print(json.dumps(json.load(response), ensure_ascii=False, indent=2))
except urllib.error.HTTPError as error:
    print('HTTP', error.code, error.read().decode())
''',
        'example.mjs': '''const response = await fetch(process.env.DEVELOPER_API_URL.replace(/\\/$/, '') + process.env.DEVELOPER_ENDPOINT, {
  method: 'POST', headers: { Authorization: `Bearer ${process.env.DEVELOPER_TOKEN}`, 'Content-Type': 'application/json' },
  body: JSON.stringify({ query: {} }), signal: AbortSignal.timeout(20000)
});
const result = await response.json();
if (!response.ok) { console.error(response.status, result); process.exitCode = 1; }
else console.log(JSON.stringify(result, null, 2));
''',
        'curl.sh': '''curl --fail-with-body --max-time 20 -X POST "$DEVELOPER_API_URL$DEVELOPER_ENDPOINT" -H "Authorization: Bearer $DEVELOPER_TOKEN" -H 'Content-Type: application/json' --data '{"query":{}}'
''',
        'README.md': f'''# 本地开发接入
无需补丁包。设置 .env.example 中的环境变量（示例不会自动加载 .env），单独领取令牌并填写 DEVELOPER_TOKEN。
Python 3 使用 python example.py；Node.js 20+ 使用 node example.mjs；或导入 postman.json 后设置环境变量。
只包含当前有效授权接口。新增授权后可重新下载资料，原令牌继续可用。平台凭证始终保留在服务端。
调用体为 {{"query":{{}},"body":{{}}}}；query 是第三方查询参数，body 是第三方 JSON 请求体。仅 Shopee 授权的 get_order_list 和 get_item_list 在 Postman 中附有查询参数示例；订单示例使用下载时生成的近 1 天 Unix 时间范围。
订单翻页检查 data.response.more；为 true 时将 data.response.next_cursor 作为下一页 query.cursor。商品翻页检查 data.response.has_next_page；为 true 时将 data.response.next_offset 作为下一页 query.offset。每页均检查平台 error；订单时间范围过期后重新生成再查询。其他平台分页参数不同，应依据对应平台文档使用并检查终止条件；网关不自动推断下一页，不自动重试写入请求。
HTTP 400 检查参数；401 检查令牌和有效期；403 申请权限或检查平台连接；429 降低频率；502 联系管理员检查第三方响应。
每次响应的 request_id 可在调用日志中查询。示例不应将令牌提交到版本库。
''',
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    response = HttpResponse(output.getvalue(), content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename="developer-app-{app.pk}.zip"'
    response['Cache-Control'] = 'no-store'
    return response
