import os, requests, json, zlib, base64
from dotenv import load_dotenv
from datetime import datetime, timedelta
load_dotenv()

kv_url   = os.environ.get('KV_REST_API_URL')
kv_token = os.environ.get('KV_REST_API_TOKEN')

r = requests.get(f'{kv_url}/get/cdr_history', headers={'Authorization': f'Bearer {kv_token}'}, timeout=10)
result = r.json().get('result')
compressed_data = base64.b64decode(result)
hist = json.loads(zlib.decompress(compressed_data).decode('utf-8'))

today = datetime.now().strftime('%Y-%m-%d')
print('Hoje:', today)
print('Datas no KV:', sorted(hist.keys()))

valid_dates = set((datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(8))
dates_to_delete = [k for k in hist.keys() if k not in valid_dates]
dates_to_keep   = [k for k in hist.keys() if k in valid_dates]
print('Seriam deletadas (> 7 dias):', sorted(dates_to_delete))
print('Seriam mantidas:', sorted(dates_to_keep))

baseline = sorted(dates_to_keep)
print('\nBaseline disponivel para diff:', baseline)
if len(baseline) == 0:
    print('PROBLEMA: Nenhuma data dentro dos 7 dias - SEM BASELINE para comparar!')
else:
    print(f'A comparacao seria: {baseline[0]} -> {today} (hoje)')
    # Conta flows disponiveis no baseline
    last = baseline[0]
    print(f'\nFlows na data baseline ({last}): {len(hist[last])}')
    for fid, calls in list(hist[last].items())[:5]:
        print(f'  {fid[:8]}...: {len(calls)} CDRs')

# Simula o diff para o primeiro flow do baseline
last_date = baseline[0] if baseline else None
if last_date:
    sample_flow_id = list(hist[last_date].keys())[0]
    prev_calls = hist[last_date][sample_flow_id]
    current_calls = prev_calls  # sem mudanca = vazio de diffs

    prev_map = {c.get('action_id'): c for c in prev_calls if c.get('action_id')}
    curr_map = {c.get('action_id'): c for c in current_calls if c.get('action_id')}

    diffs = []
    for aid, c in curr_map.items():
        if aid not in prev_map:
            diffs.append({'type': 'added', 'call': c})
    for aid, c in prev_map.items():
        if aid not in curr_map:
            diffs.append({'type': 'removed', 'call': c})

    print(f'\nSimulacao sem mudancas para flow {sample_flow_id[:8]}: {len(diffs)} diffs (esperado: 0)')

    # Agora simula com uma mudanca (remove o primeiro CDR)
    current_calls_modificado = prev_calls[1:]
    curr_map2 = {c.get('action_id'): c for c in current_calls_modificado if c.get('action_id')}
    diffs2 = []
    for aid, c in prev_map.items():
        if aid not in curr_map2:
            diffs2.append({'type': 'removed', 'call': c})
    print(f'Simulacao removendo 1 CDR: {len(diffs2)} diffs (esperado: 1)')
    if diffs2:
        print(f'  -> Detectado: {diffs2[0]["type"]} | label: {diffs2[0]["call"].get("label")}')
