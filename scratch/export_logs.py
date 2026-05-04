import os
import json
import re

base_dir = r"c:\Users\proxx\.gemini\antigravity\brain"
output_dir = r"c:\Users\proxx\OneDrive\Área de Trabalho\genesys_cdr\historico_ia"

if not os.path.exists(output_dir):
    os.makedirs(output_dir)

def clean_json_md(json_line):
    try:
        data = json.loads(json_line)
        source = data.get("source", "")
        content = data.get("content", "")
        
        # If it's a planner response with tool calls, we might want to list them
        tool_calls = data.get("tool_calls", [])
        
        timestamp = data.get("created_at", "Unknown")
        
        header = f"\n### {source} [{timestamp}]\n"
        
        if content:
            # Remove XML-like tags if needed, or keep them
            return header + content + "\n"
        elif tool_calls:
            tools = ", ".join([tc.get("name", "") for tc in tool_calls])
            return header + f"*Executou ferramentas:* {tools}\n"
        return ""
    except:
        return ""

ids = [d for d in os.listdir(base_dir) if os.path.isdir(os.path.join(base_dir, d))]

full_history = []

for cid in ids:
    log_path = os.path.join(base_dir, cid, ".system_generated", "logs", "overview.txt")
    if os.path.exists(log_path):
        with open(log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
        md_content = f"# Conversa {cid}\n"
        for line in lines:
            md_content += clean_json_md(line)
            
        filename = f"conversa_{cid[:8]}.md"
        with open(os.path.join(output_dir, filename), "w", encoding="utf-8") as f:
            f.write(md_content)
        
        full_history.append(md_content)

# Also create a combined file
with open(os.path.join(output_dir, "historico_completo.md"), "w", encoding="utf-8") as f:
    f.write("\n\n---\n\n".join(full_history))

print(f"Exportados {len(ids)} logs para {output_dir}")
