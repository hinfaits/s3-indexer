import os
import hashlib
import random
import string
from datetime import datetime
import pytz
import logging

from flask import Flask, render_template, request, session, Markup, redirect, url_for

from boto.s3.connection import S3Connection

from google.appengine.api import memcache
from google.appengine.ext.appstats import recording




PASSWORD = os.environ.get('PASSWORD')
SECRET_KEY = os.environ['SECRET_KEY']
CACHE_TTL = int(os.environ['CACHE_TTL'])
S3_LINK_TTL = int(os.environ['S3_LINK_TTL'])
BUCKET = os.environ['BUCKET']
ACCESS_KEY = os.environ['ACCESS_KEY']
SECRET_ACCESS_KEY = os.environ['SECRET_ACCESS_KEY']

def format_fsize(fsize):
    formats = {
        0: "{:03.1f} {}",
        1: "{:03.1f} {}",
        2: "{: 3.0f} {}",
        # For zero-padding instead of space padding
        # 2: "{:03.0f} {}",
        3: "{:03.0f} {}",
    }
    prefixes = ["B", "K", "M", "G", "T", "P", "E"]

    incr = 0
    while len(str(int(round(fsize)))) > 3:
        fsize = fsize / 1024.0
        incr += 1
        if incr >= len(prefixes) - 1:
            raise RuntimeError

    out_string = formats[len(str(int(round(fsize))))].format(fsize, prefixes[incr])
    return Markup(out_string.replace(" ", "&nbsp;"))


def format_timestring(dt_string):
    dt_unaware = datetime.strptime(dt_string, "%Y-%m-%dT%H:%M:%S.000Z")
    dt_aware = dt_unaware.replace(tzinfo=pytz.UTC)
    return dt_aware.strftime("%d-%b-%Y %H:%M:%S %z")


class Config(object):
    DEBUG = False
    TESTING = False
    CSRF_ENABLED = True
    SECRET_KEY = SECRET_KEY


class Entity(object):
    def __init__(self, name):
        self.name = name


class File(Entity):
    def __init__(self, name, last_modified, size, url):
        self.name = name
        self.last_modified = last_modified
        self.size = format_fsize(size)
        self.url = url
        self.ext = os.path.splitext(name)[1].replace(".", "")
        self.dir = False


class Folder(Entity):
    def __init__(self, name):
        self.name = name
        self.url = u"./{}".format(name)
        self.dir = True


def login():
    if not PASSWORD:
        # Password is not set, or is empty
        #   So we skip authentication
        return True
    secret_key = memcache.get('secret_key')
    if not secret_key:
        secret_key = ''.join(random.choice(string.ascii_uppercase + string.ascii_lowercase + string.digits) for _ in range(10))
        memcache.add('secret_key', secret_key)
    if request.form.get('password') == PASSWORD:
        session['secret_key'] = secret_key
    if session.get('secret_key') == secret_key:
        return True
    return False


app = Flask(__name__)
app.wsgi_app = recording.appstats_wsgi_middleware(app.wsgi_app)
app.config.from_object(Config)


@app.route('/', methods=['GET', 'POST'])
def home():
    return redirect(url_for("index", path=""))


@app.route('/bucket/', methods=['GET', 'POST'])
def catch_urls():
    """
    Alias for the index function at the root,
    Flask won't let us catch the root dir with the <path> variable
    """
    return index("")


@app.route('/bucket/<path:path>', methods=['GET', 'POST'])
def index(path):
    if not login():
        return render_template("login.html")
    refresh_cache = request.args.get('flush')
    page_id = hashlib.md5(path.encode('ascii', errors='ignore')).hexdigest()
    page = memcache.get(page_id)
    if page is None or refresh_cache:
        conn = S3Connection(ACCESS_KEY, SECRET_ACCESS_KEY)
        bucket = conn.get_bucket(BUCKET)
        contents = bucket.list(
            prefix=path,
            delimiter="/")
        entities = []
        for key in list(contents):
            try:
                entity = File(
                    name=key.name[len(path):],
                    last_modified=format_timestring(key.last_modified),
                    size=key.size,
                    url=key.generate_url(S3_LINK_TTL))
            except AttributeError:
                entity = Folder(
                    name=key.name[len(path):])
            entities.append(entity)
        page = render_template(
            "index.html",
            path=u"/{}".format(path),
            flush_url=u"{}?flush=1".format(request.url) if not refresh_cache else request.url,
            entities=entities)
        if not memcache.set(page_id, page, CACHE_TTL):
            logging.warning("Failed to update memcache.")
    return page


# if __name__ == '__main__':
#     app.run(host="0.0.0.0", debug=True, threaded=True)
