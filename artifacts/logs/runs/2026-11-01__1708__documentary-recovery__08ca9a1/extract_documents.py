"""Offline extraction of the six pinned source documents; optional pypdf runtime."""
import hashlib
import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pypdf

root = Path(sys.argv[1]).resolve()
output = Path(sys.argv[2])
selected = {'documentary-b01-04','documentary-b01-05','documentary-b02-04',
            'documentary-b02-05','documentary-b03-07','documentary-b03-08'}
results = []
for cf in sorted((root/'config').glob('arrival-documentary-b*.toml')):
    for c in tomllib.loads(cf.read_text())['assets'].values():
        if c['source_id'] not in selected:
            continue
        p=root/c['local_path']
        digest=hashlib.sha256(p.read_bytes()).hexdigest()
        if digest != p.with_name(p.name+'.sha256').read_text().strip():
            raise ValueError('raw checksum changed')
        if c['format']=='PDF':
            pages=[{'page':i+1,'text':p.extract_text(extraction_mode='layout')}
                   for i,p in enumerate(pypdf.PdfReader(p).pages)]
            extractor='pypdf '+pypdf.__version__+' layout'
        else:
            text=subprocess.check_output(['textutil','-convert','txt','-stdout',str(p)],text=True)
            pages=[{'page':0,'text':text}]
            extractor='macOS textutil; paragraph/line locators, original page unknown'
        results.append({'source_id':c['source_id'],'raw_path':c['local_path'],
                        'raw_sha256':digest,'url':c['url'],'extractor':extractor,'pages':pages})
if len(results)!=6:
    raise ValueError('incomplete frozen document set')
output.parent.mkdir(parents=True,exist_ok=True)
output.write_text(json.dumps(results,sort_keys=True,ensure_ascii=False,indent=2)+'\n')
print('extracted',len(results),'documents')
