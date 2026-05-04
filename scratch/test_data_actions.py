import os
import requests
from datetime import datetime, timedelta, timezone

# Substitua pelos do env
CLIENT_ID = "1a49dbf9-240b-4c36-b1e8-5f3f54d9a548"
CLIENT_SECRET = "G54C__9UMzMRVodTb9q_ul9aBgFb5-8b1jP62Duqt0sKi804QC8z4AY2S_fY"
REGION = "sae1.pure.cloud"

def get_token():
    auth_url = f"https://login.{REGION}/oauth/token"
    r = requests.post(
        auth_url,
        data={"grant_type": "client_credentials"},
        auth=(CLIENT_ID, CLIENT_SECRET)
    )
    return r.json()["access_token"]

def main():
    token = get_token()
    base_url = f"https://api.{REGION}"
    
    # query test
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=7)
    
    body = {
        "interval": f"{start.strftime('%Y-%m-%dT%H:%M:%S.000Z')}/{now.strftime('%Y-%m-%dT%H:%M:%S.000Z')}",
        "granularity": "P1D",
        "groupBy": ["actionId", "responseStatus", "errorCategory", "errorCode", "status"],
        "metrics": ["tTotalExecution"],
        "flattenMultivaluedDimensions": True
    }
    
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    
    print("Testing with status dimensions...")
    r = requests.post(f"{base_url}/api/v2/analytics/actions/aggregates/query", headers=headers, json=body)
    print(r.status_code)
    print(r.text[:1000])
    
    if r.status_code == 400:
        # Tenta sem as dimensões pra ver o que ele aceita
        body["groupBy"] = ["actionId", "responseStatus"]
        print("\nTesting with actionId and responseStatus...")
        r = requests.post(f"{base_url}/api/v2/analytics/actions/aggregates/query", headers=headers, json=body)
        print(r.status_code)
        import json
        print(json.dumps(r.json(), indent=2)[:2000])

if __name__ == "__main__":
    main()
