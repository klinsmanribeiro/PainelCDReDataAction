import sys
import os
sys.path.append(os.path.abspath(r"c:\Users\proxx\OneDrive\Área de Trabalho\genesys_cdr"))
import app
from flask import Flask
import requests

# 1. Fetch real flows directly
token = app.get_auth_token()
r = requests.get(f"https://api.{app.GENESYS_REGION}/api/v2/flows?pageSize=100", headers=app.HEADERS)
flows = r.json().get("entities", [])
vendas_flow = next((f for f in flows if "vendas v2" in f["name"].lower()), None)

if vendas_flow:
    flow_id = vendas_flow["id"]
    print(f"Testing with flow {flow_id}...")
    # Monkey patch to see action ids
    original_post = requests.post
    def mock_post(url, *args, **kwargs):
        if "analytics" in url:
            print("Query JSON:", kwargs.get("json"))
        return original_post(url, *args, **kwargs)
    requests.post = mock_post
    
    with app.app.test_request_context(
        '/api/data-actions-performance', 
        method='POST',
        json={"flowId": flow_id, "hours": 0, "startDate": "2026-04-20", "endDate": "2026-04-29", "granularity": "P1D"}
    ):
        try:
            # intercept actions_in_flow
            original_scan = app.scan_flow_for_data_actions
            def mock_scan(uri):
                res = original_scan(uri)
                print(f"Scanned {len(res)} actions. Sample: {res[:2]}")
                return res
            app.scan_flow_for_data_actions = mock_scan
            
            response = app.api_data_actions_performance()
            print("Response:", response.get_data(as_text=True)[:500])
            
            # Print if 00cb419d is in flow
            cached = app._data_actions_scan_cache.get("data") or []
            flow_cached = next((f for f in cached if f.get("flow_id") == flow_id), None)
            if flow_cached:
                actions = flow_cached.get("data_actions", [])
                found = [a for a in actions if "00cb419d" in a.get("action_id", "")]
                print("Found 00cb419d in Vendas V2?", found)
        except Exception as e:
            import traceback
            traceback.print_exc()
else:
    print("Flow Vendas V2 not found")

