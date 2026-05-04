import requests

try:
    r = requests.post("http://127.0.0.1:5051/api/data-actions-performance", json={"flowId": "b8f673ee-3f65-4fbb-ac17-fec5d1b33230", "hours": 1})
    print(r.status_code)
    print(r.text[:500])
except Exception as e:
    print(e)
