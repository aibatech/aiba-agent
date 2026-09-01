import math,re,sys
from pathlib import Path
PATTERNS=[re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),re.compile(r'\bsk-[A-Za-z0-9_-]{24,}\b'),re.compile(r'\bAKIA[0-9A-Z]{16}\b')]
SKIP={'.git','.venv','build','dist','agent_system'};findings=[]
for path in Path('.').rglob('*'):
    if not path.is_file() or any(x in path.parts for x in SKIP) or path.suffix in {'.zip','.png','.jpg','.ico'}:continue
    try:text=path.read_text(errors='ignore')
    except OSError:continue
    for pattern in PATTERNS:
        if pattern.search(text):findings.append(f'{path}: matches {pattern.pattern}')
if findings:print('\n'.join(findings));sys.exit(1)
print('Secret scan passed')
