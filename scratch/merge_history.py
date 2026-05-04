"""
Merge do histórico local (data/cdr_history.json) no KV (Upstash).
As datas do arquivo local que já existem no KV são MANTIDAS no KV.
As datas exclusivas do arquivo local são ADICIONADAS ao KV.
"""
import os, requests, json, zlib, base64
from dotenv import load_dotenv
from datetime import datetime, timedelta
load_dotenv()

kv_url   = os.environ.get('KV_REST_API_URL')
kv_token = os.environ.get('KV_REST_API_TOKEN')
headers  = {'Authorization': f'Bearer {kv_token}'}

# 1. Carrega KV
r = requests.get(f'{kv_url}/get/cdr_history', headers=headers, timeout=10)
result = r.json().get('result')
kv_hist = json.loads(zlib.decompress(base64.b64decode(result)).decode('utf-8'))
print('KV  datas:', sorted(kv_hist.keys()))

# 2. Carrega arquivo local
local_file = os.path.join(os.path.dirname(__file__), '..', 'data', 'cdr_history.json')
with open(local_file, encoding='utf-8') as f:
    local_hist = json.load(f)
print('LOC datas:', sorted(local_hist.keys()))

# 3. Merge: KV tem prioridade para datas que existem nos dois
merged = dict(kv_hist)
added_dates = []
for date, flows in local_hist.items():
    if date not in merged:
        merged[date] = flows
        added_dates.append(date)
    else:
        # Adiciona flows locais que não existem no KV para aquela data
        for fid, calls in flows.items():
            if fid not in merged[date]:
                merged[date][fid] = calls
        added_dates.append(f'{date}(flows extras)')

print('Adicionando ao KV:', added_dates)
print('Merged datas:', sorted(merged.keys()))

# 4. Salva o merged no KV
json_str = json.dumps(merged, ensure_ascii=False)
compressed = zlib.compress(json_str.encode('utf-8'))
val = base64.b64encode(compressed).decode('utf-8')

w = requests.post(f'{kv_url}/set/cdr_history', headers=headers, data=val, timeout=15)
print(f'\nSalvo no KV: {w.status_code} | {w.text[:80]}')

# 5. Confirma leitura
r2 = requests.get(f'{kv_url}/get/cdr_history', headers=headers, timeout=10)
result2 = r2.json().get('result')
hist2 = json.loads(zlib.decompress(base64.b64decode(result2)).decode('utf-8'))
print('KV após merge:', sorted(hist2.keys()))
for d, flows in sorted(hist2.items()):
    print(f'  {d}: {len(flows)} flows')
