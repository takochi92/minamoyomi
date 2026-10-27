"""Map public exhibition entry pages without opening denied playback APIs/media.

No credential extraction, player impersonation, origin changes, or media fetches.
Raw HTML remains private; receipts retain only public route classifications.
"""
import argparse
import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit, parse_qs
from urllib.request import urlopen

ALLOWED_HOSTS = {'www.heiwajima.gr.jp', 'race.boatcast.jp', 'front.player.boatrace-cdn.jp'}


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if key in ('src', 'href') and value:
                self.links.append((tag, value))


def classify(page_url, body):
    parser = Links()
    parser.feed(body)
    items = list(parser.links)
    items += [('inline', value) for value in re.findall(r'https?://[^\s<>"\x27]+', body)]
    found = set()
    for tag, value in items:
        url = urlsplit(urljoin(page_url, value.replace('&amp;', '&')))
        host = url.hostname or ''
        if host not in ALLOWED_HOSTS or url.scheme != 'https':
            continue
        if host == 'front.player.boatrace-cdn.jp' and url.path == '/player/vod':
            q = parse_qs(url.query)
            found.add((tag, host, url.path, q.get('service', [''])[0], q.get('stadium', [''])[0],
                       q.get('raceType', [''])[0]))
        elif tag in ('iframe', 'script'):
            # No query values or unrecognised payloads enter the public receipt.
            found.add((tag, host, url.path, '', '', ''))
    return [{'element': tag, 'host': host, 'path': path, 'service': service,
             'stadium': stadium, 'race_type': race_type}
            for tag,host,path,service,stadium,race_type in sorted(found)]


def run(directory, opener=urlopen):
    directory = Path(directory).resolve()
    public = Path(__file__).resolve().parents[1]/'site'
    if directory == public or public in directory.parents:
        raise ValueError('private_storage_required')
    directory.mkdir(parents=True, exist_ok=False)
    entries = {
        'heiwajima_official_movie': 'https://www.heiwajima.gr.jp/replay/replay_movie/race/2026102601.htm?type=1',
        'boatcast_exhibition_entry': 'https://race.boatcast.jp/replay?jo=04&md=T',
    }
    rows = []
    queue = list(entries.items())
    seen = set()
    while queue and len(rows) < 7:
        name, url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        parsed = urlsplit(url)
        row = {'entry': name, 'page': parsed.scheme+'://'+parsed.netloc+parsed.path,
               'query_keys': sorted(parse_qs(parsed.query)), 'media_downloaded': False}
        try:
            with opener(url, timeout=30) as response:
                if urlsplit(response.geturl()).hostname not in ALLOWED_HOSTS:
                    raise ValueError('unexpected_page_redirect')
                data = response.read(2_000_001)
                if len(data) > 2_000_000:
                    raise ValueError('public_page_size_limit')
                row['status'] = response.status
            (directory/(name+'.html')).write_bytes(data)
            body = data.decode('utf-8', errors='replace')
            row.update(html_sha256=hashlib.sha256(data).hexdigest(), routes=classify(url, body))
            parser = Links()
            parser.feed(body)
            for tag, value in parser.links:
                child = urljoin(url, value.replace('&amp;', '&'))
                target = urlsplit(child)
                if target.scheme != 'https' or target.hostname not in ALLOWED_HOSTS:
                    continue
                if any(re.search(r'key|token|sig|auth', key, re.I) for key in parse_qs(target.query)):
                    continue
                is_public_wrapper = tag == 'iframe' and target.hostname == 'www.heiwajima.gr.jp'
                is_routing_script = tag == 'script' and target.path in ('/js/replay.js', '/assets/js/main.js')
                if is_public_wrapper or is_routing_script:
                    queue.append((name+'-child-'+str(len(queue)), child))
        except HTTPError as error:
            row.update(status=error.code, state='denied_stop_no_retry' if error.code in (401,403) else 'http_error')
        except URLError:
            row.update(state='network_error')
        rows.append(row)
    receipt = {'entries': rows, 'denied_playback_api_retried': False,
               'source_address_changed': False, 'credentials_extracted': False,
               'external_acquisition_operational': False}
    (directory/'receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--private-output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.private_output), ensure_ascii=False, indent=2))
