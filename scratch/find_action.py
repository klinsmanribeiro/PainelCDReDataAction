import sys
import os
sys.path.append(os.path.abspath(r"c:\Users\proxx\OneDrive\Área de Trabalho\genesys_cdr"))
import app
import requests

token = app.get_auth_token()
r = requests.get(f"https://api.{app.GENESYS_REGION}/api/v2/flows?pageSize=100", headers=app.HEADERS)
flows = r.json().get("entities", [])
vendas_flow = next((f for f in flows if "vendas v2" in f["name"].lower()), None)

if vendas_flow:
    print(vendas_flow["id"])
    flow_id = vendas_flow["id"]
    r2 = requests.get(f"https://api.{app.GENESYS_REGION}/api/v2/flows/{flow_id}", headers=app.HEADERS)
    pub = r2.json().get("publishedVersion") or r2.json().get("checkedInVersion") or {}
    cfg_uri = pub.get("configurationUri", "")
    actions = app.scan_flow_for_data_actions(cfg_uri)
    found = [a for a in actions if "00cb419d" in a.get("action_id", "")]
    print("Found in Vendas V2:", found)
    
    # Filter by these action IDs
    action_ids = [a.get("action_id") for a in actions]
    
    body = {
        "interval": "2026-04-20T00:00:00.000Z/2026-04-29T23:59:59.000Z",
        "granularity": "P1D",
        "groupBy": ["actionId", "responseStatus"],
        "metrics": ["tTotalExecution"],
        "flattenMultivaluedDimensions": True,
        "filter": {
            "type": "or",
            "predicates": [
                {"type": "dimension", "dimension": "actionId", "operator": "matches", "value": f".*{aid}$"}
                for aid in action_ids[:20] # max 20 predicates maybe?
            ]
        }
    }
    print("Querying analytics for these actions...")
    r3 = requests.post(f"https://api.{app.GENESYS_REGION}/api/v2/analytics/actions/aggregates/query", headers=app.HEADERS, json=body)
    print(r3.status_code)
    import json
    print(json.dumps(r3.json(), indent=2)[:500])

