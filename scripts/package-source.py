"""Create the downloadable project without data, credentials, QA files or nested ZIPs."""
from pathlib import Path
import zipfile
ROOT=Path(__file__).resolve().parents[1]
output=ROOT/'dist/downloads/Haven-Realty-Source.zip'
output.parent.mkdir(parents=True,exist_ok=True)
allowed={'.env.example','.gitignore','FONT-LICENSES.txt','README.md','requirements.txt','requirements-dev.txt','start-windows.cmd','start-macos.sh','docker-compose.yml'}
with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
    for p in sorted(ROOT.rglob('*')):
        if not p.is_file():continue
        rel=p.relative_to(ROOT)
        if any(part in {'data','.git','.openai','.venv','__pycache__','.pytest_cache','downloads'} for part in rel.parts):continue
        if rel.name.startswith('qa-'):continue
        if rel.parts[0] not in {'backend','dist','scripts','tests','samples'} and str(rel) not in allowed:continue
        archive.write(p,Path('Haven-Realty')/rel)
print(output)
with zipfile.ZipFile(output) as archive:
    assert not any('/.env' in n and not n.endswith('.env.example') for n in archive.namelist())
    assert not any('/data/' in n for n in archive.namelist())
    assert archive.testzip() is None
    print(f'{len(archive.namelist())} source/assets files, {output.stat().st_size:,} bytes')
