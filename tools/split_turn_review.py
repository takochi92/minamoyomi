"""Export the local review page with separate images; no network or publication."""
import argparse
import base64
import hashlib
import json
import re
from pathlib import Path


def split_review(source, destination):
    source=Path(source);destination=Path(destination)
    text=source.read_text(encoding='utf-8')
    marker=re.search(r'(<script type="application/json" id="bundle">)(.*?)(</script>)',text,re.S)
    if not marker:raise ValueError('review_bundle_missing')
    bundle=json.loads(marker[2]);images=bundle.get('images')
    if not isinstance(images,dict) or not 1<=len(images)<=5000:raise ValueError('invalid_images')
    assets={};paths={}
    for key,value in images.items():
        if not isinstance(value,str) or not value.startswith('data:image/webp;base64,'):
            raise ValueError('embedded_webp_required')
        data=base64.b64decode(value.split(',',1)[1],validate=True)
        if not 12<=len(data)<25*1024*1024 or data[:4]!=b'RIFF' or data[8:12]!=b'WEBP':
            raise ValueError('invalid_webp_or_size')
        name=hashlib.sha256(data).hexdigest()+'.webp';assets[name]=data;paths[key]='frames/'+name
    # Only media locations change. Original frame clocks, labels and evidence fingerprints stay intact.
    payload=json.dumps({**bundle,'images':paths},ensure_ascii=False,allow_nan=False).replace('<','\\u003c')
    output=text[:marker.start(2)]+payload+text[marker.end(2):]
    if len(output.encode())>=25*1024*1024:raise ValueError('html_size_limit')
    destination.mkdir(parents=True,exist_ok=False)
    (destination/'frames').mkdir()
    for name,data in assets.items():(destination/'frames'/name).write_bytes(data)
    (destination/'index.html').write_text(output,encoding='utf-8')
    return {'images':len(assets),'html_bytes':len(output.encode()),'largest_image_bytes':max(map(len,assets.values())),
            'external_publication_performed':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path);parser.add_argument('destination',type=Path)
    args=parser.parse_args()
    print(json.dumps(split_review(args.source,args.destination)))
