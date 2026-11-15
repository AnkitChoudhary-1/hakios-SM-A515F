import json

with open(r'C:\Users\Ankit\.gemini\antigravity\brain\8565586b-538a-48bf-8680-9d7d62fd6af0\.system_generated\logs\transcript.jsonl', 'r', encoding='utf-8') as f:
    for line in f:
        obj = json.loads(line)
        idx = obj.get('step_index', 0)
        if 2660 <= idx <= 2710:
            tc = obj.get('tool_calls', [])
            summary = []
            for c in tc:
                name = c.get('name')
                args = c.get('args', {})
                summary.append(f"{name}: {args.get('toolSummary') or args.get('Path') or args.get('CommandLine', '')[:50]}")
            print(f"Step {idx} ({obj.get('type')}): {', '.join(summary)}")

