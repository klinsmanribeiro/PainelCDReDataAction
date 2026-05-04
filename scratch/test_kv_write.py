import os, requests, json, zlib, base64
from dotenv import load_dotenv
from datetime import datetime, timedelta
load_dotenv()

kv_url   = os.environ.get('KV_REST_API_URL')
kv_token = os.environ.get('KV_REST_API_TOKEN')
headers  = {'Authorization': f'Bearer {kv_token}'}

# 1. Carrega histórico atual
r = requests.get(f'{kv_url}/get/cdr_history', headers=headers, timeout=10)
result = r.json().get('result')
hist = json.loads(zlib.decompress(base64.b64decode(result)).decode('utf-8'))

today = datetime.now().strftime('%Y-%m-%d')
print('=== ESTADO ATUAL ===')
print('Hoje:', today)
print('Datas no KV:', sorted(hist.keys()))

# 2. Verifica se hoje já tem snapshot
print('\n=== SNAPSHOT DE HOJE ===')
if today in hist:
    print(f'Ja existe snapshot para hoje: {len(hist[today])} flows')
else:
    print('Nenhum snapshot para hoje ainda (sera criado na proxima varredura)')

# 3. Verifica a janela de 7 dias
valid_dates = set((datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(8))
baseline_dates = sorted(k for k in hist.keys() if k in valid_dates and k != today)
print('\n=== BASELINE PARA DIFF ===')
print('Datas validas (7 dias):', sorted(valid_dates))
print('Datas com dados no KV:', baseline_dates)

if not baseline_dates:
    print('\nPROBLEMA CRITICO: Nenhuma data de referencia dentro da janela de 7 dias!')
    print('O KV tem dados apenas de:', sorted(hist.keys()))
    oldest = sorted(hist.keys())[-1] if hist else None
    if oldest:
        days_ago = (datetime.now() - datetime.strptime(oldest, '%Y-%m-%d')).days
        print(f'O dado mais recente ({oldest}) e de {days_ago} dia(s) atras')
        if days_ago > 7:
            print('ESSE DADO SERA DELETADO na proxima varredura — sem baseline restante!')
else:
    b = baseline_dates[-1]
    flows_in_b = len(hist[b])
    print(f'\nBaseline: {b} com {flows_in_b} flows')
    print('A proxima varredura comparara os flows atuais contra', b)

# 4. Teste de escrita no KV
print('\n=== TESTE DE ESCRITA NO KV ===')
test_payload = {'_test': True, 'ts': today}
test_str = json.dumps(test_payload)
compressed = zlib.compress(test_str.encode('utf-8'))
val = base64.b64encode(compressed).decode('utf-8')
w = requests.post(f'{kv_url}/set/cdr_history_test', headers=headers, data=val, timeout=10)
print(f'Write status: {w.status_code} | body: {w.text[:100]}')

rr = requests.get(f'{kv_url}/get/cdr_history_test', headers=headers, timeout=10)
rresult = rr.json().get('result')
if rresult:
    decoded = json.loads(zlib.decompress(base64.b64decode(rresult)).decode('utf-8'))
    print(f'Read back OK: {decoded}')
else:
    print('FALHA ao ler de volta o dado de teste!')
