from flask import Flask, render_template, request

from boto.s3.connection import S3Connection

from google.appengine.api import memcache
from google.appengine.ext.appstats import recording

import os
import hashlib
from datetime import datetime

import logging

CACHE_TTL = int(os.environ['CACHE_TTL'])
S3_LINK_TTL = int(os.environ['S3_LINK_TTL'])
BUCKET = os.environ['BUCKET']
ACCESS_KEY = os.environ['ACCESS_KEY']
SECRET_ACCESS_KEY = os.environ['SECRET_ACCESS_KEY']


def format_fsize(fsize):
    prefixes = ["B", "K", "M", "G", "T", "P", "E"]

    incr = 0
    while len(str(int(round(fsize)))) > 3:
        fsize = fsize / 1024
        incr += 1
        if incr >= len(prefixes) - 1:
            break

    if len(str(int(fsize))) == 3:
        return str("{:03.0f} {}".format(fsize, prefixes[incr]))
    if len(str(int(fsize))) == 2:
        return str("{: 3.0f} {}".format(fsize, prefixes[incr]))
    if len(str(int(fsize))) == 1:
        return str("{:03.1f} {}".format(fsize, prefixes[incr]))


def format_timestring(dt):
    return (
            datetime.strptime(dt, "%Y-%m-%dT%H:%M:%S.000Z")
        ).strftime("%d-%b-%Y %H:%M:%S")


class Config(object):
    DEBUG = False
    TESTING = False
    CSRF_ENABLED = True
    SECRET_KEY = ""


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


app = Flask(__name__)
app.wsgi_app = recording.appstats_wsgi_middleware(app.wsgi_app)
app.config.from_object(Config)


@app.route('/')
def home():
    """
    Redirect to the index function
    The interpreted won't let us catch the root dir
      with the <path> variable
    """
    return index("")


@app.route('/<path:path>')
def index(path):
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


if __name__ == '__main__':
    app.run(host="0.0.0.0", debug=True, threaded=True)
