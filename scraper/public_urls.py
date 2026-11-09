"""Public HTML routes, independent of Cloudflare Pages' on-disk filenames."""
import re
from urllib.parse import urljoin, urlsplit, urlunsplit


def public_url(url):
    parts = urlsplit(url)
    path = parts.path
    if path.endswith('index.html') and (path == 'index.html' or path.endswith('/index.html')):
        path = path[:-10] or '/'
    elif path.endswith('.html'):
        path = path[:-5]
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))


def html_links(html, page_path, site_url):
    """Normalize legacy literal links as well as links built through Page.u."""
    base = site_url + public_url('/' + page_path)

    def replace(match):
        target = match[2]
        resolved = urljoin(base, target)
        if urlsplit(resolved).netloc != urlsplit(site_url).netloc:
            return match[0]
        if not urlsplit(resolved).path.endswith('.html'):
            return match[0]
        return match[1] + public_url(resolved).removeprefix(site_url) + match[3]

    return re.sub(r'''(\s(?:href|action)=["'])([^"'?#]*\.html(?:[?#][^"']*)?)(["'])''', replace, html)
