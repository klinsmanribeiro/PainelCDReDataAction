import json
import requests
import os
import zlib
import base64

HISTORY_FILE = os.path.join("data", "cdr_history.json")

print("="*60)
print("🚀 UPLOAD COMPACTADO PARA VERCEL KV")
print("="*60)
print("Necessário para contornar o limite de 1MB do plano gratuito.")
print("-" * 60)

kv_url = input("Cole aqui a URL do KV: ").strip()
kv_token = input("Cole aqui o TOKEN do KV: ").strip()

if not kv_url or not kv_token:
    print("⚠️ Dados incompletos.")
    exit(1)

if kv_url.endswith("/"): kv_url = kv_url[:-1]

try:
    print(f"Lendo {HISTORY_FILE}...")
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        data_raw = f.read()
    
    # Valida JSON
    json.loads(data_raw)
    
    print("📦 Compactando dados...")
    compressed = zlib.compress(data_raw.encode('utf-8'))
    data_to_send = base64.b64encode(compressed).decode('utf-8')
    
    orig_size = len(data_raw) / 1024
    new_size = len(data_to_send) / 1024
    print(f"✓ Redução: {orig_size:.1f}KB -> {new_size:.1f}KB (Economia de {100-(new_size/orig_size*100):.1f}%)")

    print("\nEnviando...")
    r = requests.post(
        f"{kv_url}/set/cdr_history", 
        headers={"Authorization": f"Bearer {kv_token}"}, 
        data=data_to_send,
        timeout=20
    )
    
    if r.status_code == 200:
        print("✅ SUCESSO! Histórico enviado com compressão.")
        print("Agora atualize o seu app no Vercel (Redeploy) e teste o Escanear!")
    else:
        print(f"❌ Erro HTTP {r.status_code}: {r.text}")
        
except Exception as e:
    print(f"❌ Erro: {e}")
