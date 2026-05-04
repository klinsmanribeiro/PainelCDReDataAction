import os, requests, json, zlib, base64
from dotenv import load_dotenv
from datetime import datetime, timedelta
load_dotenv()

kv_url   = os.environ.get('KV_REST_API_URL')
kv_token = os.environ.get('KV_REST_API_TOKEN')
headers  = {'Authorization': f'Bearer {kv_token}'}

r = requests.get(f'{kv_url}/get/cdr_history', headers=headers, timeout=10)
hist = json.loads(zlib.decompress(base64.b64decode(r.json()['result'])).decode('utf-8'))

today = datetime.now().strftime('%Y-%m-%d')
valid = set((datetime.now()-timedelta(days=i)).strftime('%Y-%m-%d') for i in range(8))
dates = sorted(k for k in hist if k in valid)
print('Datas na janela de 7 dias:', dates)

# Verifica diffs em todos os flows entre datas consecutivas
total_diffs = 0
for i in range(1, len(dates)):
    prev_d = dates[i-1]
    curr_d = dates[i]
    flows_prev = set(hist.get(prev_d, {}).keys())
    flows_curr = set(hist.get(curr_d, {}).keys())

    for fid in flows_prev | flows_curr:
        prev_calls = hist.get(prev_d, {}).get(fid, [])
        curr_calls = hist.get(curr_d, {}).get(fid, [])
        prev_map = {c['action_id']: c for c in prev_calls if c.get('action_id')}
        curr_map = {c['action_id']: c for c in curr_calls if c.get('action_id')}
        added   = [c for aid, c in curr_map.items() if aid not in prev_map]
        removed = [c for aid, c in prev_map.items() if aid not in curr_map]
        if added or removed:
            total_diffs += len(added) + len(removed)
            print(f'\nFlow {fid[:8]}... | {prev_d} -> {curr_d}')
            for c in added:
                print(f'  + {c.get("label", "?")}  [#{c.get("tracking_id", "")}]')
            for c in removed:
                print(f'  - {c.get("label", "?")}  [#{c.get("tracking_id", "")}]')

print(f'\nTotal de mudancas detectadas no historico: {total_diffs}')
