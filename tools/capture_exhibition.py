"""Server-side research capture through the official player's normal UI.

No extracted API credentials, login sessions, DRM licenses or TLS bypass.
Signed media URLs and transport keys stay in a temporary private directory.
Only numeric summaries are safe to retain publicly.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit, urljoin
from urllib.request import urlopen

from tools.update_exhibition import official_player


def media_url(value):
    try:
        url=urlsplit(value)
        return (url.scheme=='https' and not url.username and not url.password and url.port in (None,443)
                and any(url.hostname==host or url.hostname.endswith('.'+host) for host in ('streaks.jp','boatrace-cdn.jp')))
    except (ValueError,TypeError,AttributeError):
        return False


def discover_master(day, race):
    # Imported only in the dedicated browser/media job, not ordinary predictions.
    from playwright.sync_api import sync_playwright
    observed=[]
    def response_seen(response):
        url=response.url
        if response.status==200 and media_url(url) and urlsplit(url).hostname=='manifest.streaks.jp' and '.m3u8' in urlsplit(url).path:
            if url not in observed:observed.append(url)
    with sync_playwright() as playwright:
        # GitHub's Ubuntu image already includes vendor Chrome and its codecs.
        # Do not reinstall a browser/OS dependencies on every race update.
        browser=playwright.chromium.launch(channel='chrome',headless=True)
        try:
            context=browser.new_context() # No personal cookies or stored login.
            page=context.new_page();page.on('response',response_seen)
            page.goto(official_player(day,race),wait_until='domcontentloaded',timeout=30000)
            page.get_by_role('button',name='Play Video',exact=True).click(timeout=20000)
            deadline=time.monotonic()+20
            while not observed and time.monotonic()<deadline:page.wait_for_timeout(250)
            if len(observed)!=1:raise ValueError('official_master_not_observed')
            return observed[0]
        finally:
            browser.close()


def fetch(url, limit, opener=urlopen):
    if not media_url(url):raise ValueError('unapproved_media_url')
    with opener(url,timeout=25) as response:
        if not media_url(response.geturl()):raise ValueError('unapproved_media_redirect')
        content=response.read(limit+1)
    if len(content)>limit:raise ValueError('media_size_limit')
    return content


def choose_variant(master, text):
    variants=[];meta=None
    if not text.startswith('#EXTM3U'):raise ValueError('invalid_master')
    for line in text.splitlines():
        if line.startswith('#EXT-X-STREAM-INF:'):meta=line
        elif meta and line and not line.startswith('#'):
            match=re.search(r'RESOLUTION=(\d+)x(\d+)',meta)
            if match and int(match[2])<=1080:
                url=urljoin(master,line)
                if media_url(url):variants.append((int(match[2]),url))
            meta=None
    if not variants:raise ValueError('video_variant_missing')
    return max(variants)


def selected_segments(base,text):
    if not text.startswith('#EXTM3U') or any(t in text for t in ('#EXT-X-MAP:','#EXT-X-BYTERANGE:')):
        raise ValueError('unsupported_media_container')
    sequence=0;elapsed=0;duration=None;tag=None;segments=[]
    for line in text.splitlines():
        if line.startswith('#EXT-X-MEDIA-SEQUENCE:'):sequence=int(line.split(':')[1])
        elif line.startswith('#EXT-X-KEY:'):
            tag=line
            if 'METHOD=NONE' not in tag and ('METHOD=AES-128' not in tag or ('KEYFORMAT=' in tag and 'KEYFORMAT="identity"' not in tag)):
                raise ValueError('protected_media_not_supported')
        elif line.startswith('#EXTINF:'):duration=float(line.split(':')[1].split(',')[0])
        elif line and not line.startswith('#') and duration is not None:
            if not 0<duration<=20:raise ValueError('invalid_segment_duration')
            url=urljoin(base,line)
            if not media_url(url):raise ValueError('unapproved_segment_url')
            segments.append((sequence,elapsed,duration,url,tag));elapsed+=duration;sequence+=1;duration=None
    if not 120<=elapsed<=900:raise ValueError('unexpected_exhibition_duration')
    start,end=max(0,elapsed-150),elapsed-35
    chosen=[s for s in segments if s[1]+s[2]>start and s[1]<end]
    if not 1<=len(chosen)<=32 or sum(s[2] for s in chosen)>135:raise ValueError('segment_count_or_duration_limit')
    return elapsed,chosen


def capture(day,race,directory,*,discover=discover_master,reader=fetch):
    start=time.monotonic();directory=Path(directory)
    # Only a newly created directory is accepted; never overwrite a prior import.
    directory.mkdir(parents=True,exist_ok=False)
    master=discover(day,race)
    height,variant=choose_variant(master,reader(master,512_000).decode('utf-8'))
    duration,segments=selected_segments(variant,reader(variant,512_000).decode('utf-8'))
    playlist=['#EXTM3U','#EXT-X-VERSION:3','#EXT-X-TARGETDURATION:20',f'#EXT-X-MEDIA-SEQUENCE:{segments[0][0]}']
    keys={};total=0
    for i,(sequence,when,length,url,tag) in enumerate(segments):
        if tag and 'METHOD=NONE' not in tag:
            match=re.search(r'URI="([^"]+)"',tag)
            if not match:raise ValueError('transport_key_missing')
            key_url=urljoin(variant,match[1])
            if key_url not in keys:
                key=reader(key_url,32)
                if len(key)!=16:raise ValueError('unexpected_transport_key')
                name=f'key-{len(keys)}.bin';(directory/name).write_bytes(key);keys[key_url]=name
            iv=re.search(r'IV=(0x[0-9a-fA-F]+)',tag);iv=iv[1] if iv else '0x'+format(sequence,'032x')
            playlist.append(f'#EXT-X-KEY:METHOD=AES-128,URI="{keys[key_url]}",IV={iv}')
        else:playlist.append('#EXT-X-KEY:METHOD=NONE')
        data=reader(url,12_000_000);total+=len(data)
        if total>250_000_000:raise ValueError('total_import_size_limit')
        name=f'segment-{i:02}.ts';(directory/name).write_bytes(data);playlist.extend([f'#EXTINF:{length},',name])
    playlist.append('#EXT-X-ENDLIST');(directory/'local.m3u8').write_text('\n'.join(playlist),encoding='utf-8')
    ffmpeg=shutil.which('ffmpeg')
    if not ffmpeg:raise ValueError('ffmpeg_required')
    target=directory/'replay.ts'
    result=subprocess.run([ffmpeg,'-y','-v','error','-nostdin','-protocol_whitelist','file,crypto,data',
        '-allowed_extensions','ts,m3u8,bin','-copyts','-i',str(directory/'local.m3u8'),'-map','0:v:0',
        '-an','-c','copy','-avoid_negative_ts','disabled',str(target)],capture_output=True,timeout=90)
    if result.returncode:raise ValueError('local_transport_decode_failed')
    summary={'date':day,'jcd':'04','rno':race,'height':height,'full_duration_seconds':duration,
        'selected_start_seconds':segments[0][1],'selected_duration_seconds':sum(s[2] for s in segments),
        'source_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'elapsed_seconds':round(time.monotonic()-start,2),
        'publication_ready':False,'prediction_used':False}
    (directory/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    return target,summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date',required=True);parser.add_argument('--race',type=int,required=True)
    parser.add_argument('--private-output',type=Path,required=True)
    args=parser.parse_args()
    # Validate before opening a browser or creating any files.
    official_player(args.date,args.race)
    try:
        _,summary=capture(args.date,args.race,args.private_output)
        print(json.dumps(summary))
    except Exception as error:
        # Do not print exceptions containing signed network URLs or transport keys.
        print(json.dumps({'date':args.date,'rno':args.race,'capture_failed':True,'error_type':type(error).__name__}))
        raise SystemExit(1)


if __name__=='__main__':main()
