"""Incrementally compile the owned core into an existing staged onedir app.

No dependency/vendor rebuild. Requires the exact base executable SHA and matching
Python bytecode magic. Unchanged PYZ modules and PKG members are preserved byte for
byte. Never operates on /Applications. Full build remains build_app.sh.
"""
import argparse
import hashlib
import importlib.util
import io
import json
import marshal
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from PyInstaller.archive.readers import CArchiveReader
from PyInstaller.archive.writers import CArchiveWriter
from PyInstaller.utils import osx
from PyInstaller.building.utils import replace_filename_in_code_object

ROOT = Path(__file__).resolve().parents[2]

def sha(data): return hashlib.sha256(data).hexdigest()

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--app',type=Path,required=True)
    p.add_argument('--base-sha',required=True)
    p.add_argument('--base-ref',default='HEAD',help='Git source matching the frozen baseline')
    p.add_argument('--finance-security',action='store_true',help='Compile only the existing owned Aleph embedding patch into staged Finance')
    args=p.parse_args()
    app=args.app.resolve()
    base_ref=subprocess.check_output(['git','rev-parse','--verify',args.base_ref+'^{commit}'],cwd=ROOT).decode().strip()
    if app.name!='Aleph.app' or str(app).startswith('/Applications/'):
        raise SystemExit('Only a staged Aleph.app outside /Applications is allowed')
    finance_rel='third_party/vibetrading/agent/src/api/security.py'
    stub=app/('Contents/Frameworks/third_party/vibetrading/bin/vibe_trading_backend/vibe_trading_backend'
              if args.finance_security else 'Contents/MacOS/aleph_sidecar')
    original=stub.read_bytes()
    if sha(original)!=args.base_sha: raise SystemExit('Base executable SHA mismatch')
    archive=CArchiveReader(str(stub))
    pyz=archive.extract('PYZ.pyz')
    if pyz[4:8]!=importlib.util.MAGIC_NUMBER: raise SystemExit('Python bytecode magic mismatch')
    offset=struct.unpack('!i',pyz[8:12])[0]
    toc=dict(marshal.loads(pyz[offset:]))
    changed=([finance_rel] if args.finance_security else subprocess.check_output(['git','diff','--name-only',base_ref,'--',
        'platform','product/backend/app','product/app/design','product/belts','catalog'],cwd=ROOT).decode().splitlines())
    compiled={}
    for rel in changed:
        source=ROOT/rel
        if source.suffix!='.py' or source.name.startswith(('test_', 'verify_')): continue
        if args.finance_security:
            names=['src.api.security']
        elif rel.startswith('product/backend/app/'):
            names=[rel.removeprefix('product/backend/').removesuffix('.py').replace('/','.')]
        else:
            names=[n for n in toc if n.split('.')[-1]==source.stem]
        baseline=subprocess.check_output(['git','show',f'{base_ref}:{rel}'],cwd=ROOT)
        matched=[]
        for name in names:
            if name not in toc:
                if args.finance_security or rel.startswith('product/backend/app/'): raise SystemExit(f'Missing core module: {name}')
                continue
            kind,start,length=toc[name]
            oldcode=marshal.loads(zlib.decompress(pyz[start:start+length]))
            basecode=compile(baseline,oldcode.co_filename,'exec',dont_inherit=True,optimize=0)
            basecode=replace_filename_in_code_object(basecode,oldcode.co_filename)
            if oldcode!=basecode:
                if args.finance_security or rel.startswith('product/backend/app/'):
                    raise SystemExit(f'Base source does not match frozen module: {name}')
                continue
            matched.append(name)
            code=compile(source.read_bytes(),oldcode.co_filename,'exec',dont_inherit=True,optimize=0)
            code=replace_filename_in_code_object(code,oldcode.co_filename)
            compiled[name]=marshal.dumps(code)
        if names and not matched:
            raise SystemExit(f'No exact baseline module match for {rel}')
    if not compiled: raise SystemExit('No owned core modules to compile')
    stream=io.BytesIO(pyz[:17]); stream.seek(17); newtoc=[]
    for name,(kind,start,length) in toc.items():
        data=zlib.compress(compiled[name],6) if name in compiled else pyz[start:start+length]
        newtoc.append((name,(kind,stream.tell(),len(data))))
        stream.write(data)
    newoffset=stream.tell();stream.write(marshal.dumps(newtoc))
    stream.seek(8);stream.write(struct.pack('!i',newoffset))
    newpyz=stream.getvalue()
    stream=io.BytesIO(); pkgtoc=[]
    for name,(start,length,rawlen,flag,kind) in archive.toc.items():
        data=original[archive._start_offset+start:archive._start_offset+start+length]
        if name=='PYZ.pyz':
            rawlen=len(newpyz);data=zlib.compress(newpyz,9) if flag else newpyz
        pkgtoc.append((stream.tell(),len(data),rawlen,flag,kind,name));stream.write(data)
    for option in archive.options: pkgtoc.append((0,0,0,0,'o',option))
    pkgoffset=stream.tell(); encoded=CArchiveWriter._serialize_toc(pkgtoc);stream.write(encoded)
    cookie=struct.unpack(archive._COOKIE_FORMAT,original[archive._end_offset-archive._COOKIE_LENGTH:archive._end_offset])
    if cookie[4]!=sys.version_info.major*100+sys.version_info.minor:
        raise SystemExit('Python version mismatch')
    stream.write(struct.pack(archive._COOKIE_FORMAT,cookie[0],stream.tell()+archive._COOKIE_LENGTH,
        pkgoffset,len(encoded),cookie[4],cookie[5]))
    pkg=stream.getvalue()
    with tempfile.TemporaryDirectory(prefix='aleph-core-compile-') as temp:
        output=Path(temp)/'aleph_sidecar'; pkgpath=Path(temp)/'core.pkg'
        shutil.copy2(stub,output);osx.remove_signature_from_binary(str(output))
        unsigned=output.read_bytes();base=CArchiveReader(str(output))._start_offset
        pkgpath.write_bytes(pkg);output.write_bytes(unsigned[:base]+pkg)
        osx.update_exe_identifier(str(output),str(pkgpath))
        osx.fix_exe_for_code_signing(str(output));osx.sign_binary(str(output))
        rebuilt=CArchiveReader(str(output)); rebuiltpyz=rebuilt.extract('PYZ.pyz')
        end=struct.unpack('!i',rebuiltpyz[8:12])[0]; rtoc=dict(marshal.loads(rebuiltpyz[end:]))
        if set(rtoc)!=set(toc): raise SystemExit('PYZ member mismatch')
        for name,(kind,start,length) in rtoc.items():
            blob=rebuiltpyz[start:start+length]
            if name in compiled:
                if zlib.decompress(blob)!=compiled[name]: raise SystemExit(f'Compile verification failed: {name}')
            else:
                _,oldstart,oldlength=toc[name]
                if blob!=pyz[oldstart:oldstart+oldlength]: raise SystemExit(f'Unchanged module differs: {name}')
        for name in archive.toc:
            if name!='PYZ.pyz' and rebuilt.extract(name)!=archive.extract(name):
                raise SystemExit(f'Unchanged PKG member differs: {name}')
        shutil.copy2(output,stub)
    copied=[]
    for rel in changed:
        source=ROOT/rel; dest=app/'Contents/Frameworks'/rel
        if dest.is_file() and source.is_file():
            shutil.copy2(source,dest)
            if dest.read_bytes()!=source.read_bytes(): raise SystemExit(f'Data copy differs: {rel}')
            copied.append(rel)
        elif rel.startswith('product/app/design/') and source.is_file():
            raise SystemExit(f'Missing house UI asset: {rel}')
    print(json.dumps(dict(base_sha=args.base_sha,base_ref=base_ref,sha=sha(stub.read_bytes()),python=sys.version,
        compiled=sorted(compiled),unchanged_pyz=len(toc)-len(compiled),copied=copied),indent=2))

if __name__=='__main__': main()
