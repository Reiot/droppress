#!/usr/bin/python
# -*- coding: utf-8 -*-
__version__ = '0.1.0'

import logging
import sys
reload(sys)
sys.setdefaultencoding("utf-8")
import os
import re
import shutil
from collections import Counter, defaultdict
from datetime import datetime

from jinja2 import Environment, PackageLoader
import markdown
import yaml
import feedgenerator
import json


logging.basicConfig()
logging.getLogger().setLevel(logging.INFO)


ACTIONS = ('generate', 'clean', 'run', 'deploy', 'new_post')
APP_INFO = dict(
    title='DropPress',
    version=__version__,
    url='http://github.com/Reiot/droppress',
)
# load config.yaml
config = yaml.load(open("config.yaml").read())

DROPBOX_APP_DIR = os.path.join(config['dropbox_dir'], 'Apps', APP_INFO['title'])
POSTS_DIR = os.path.join(DROPBOX_APP_DIR, 'posts')
DEPLOY_DIR = os.path.join(DROPBOX_APP_DIR, 'deploy')
ASSETS_DIR = os.path.join(os.getcwd(), 'assets')
GIT = config.get('git', '/usr/bin/git')
LOCALLY = config.get('locally', '/usr/local/bin/locally')
EDITOR = config.get('editor', '/Applications/Sublime\ Text\ 2.app/Contents/SharedSupport/bin/subl')
PAGINATION_SIZE = 6

def init():
    if not os.path.exists(DROPBOX_APP_DIR):
        logging.info('create DropBox app dir..')
        os.mkdirs(DROPBOX_APP_DIR)

    if not os.path.exists(POSTS_DIR):
        logging.info('create posts dir..')
        os.mkdirs(POSTS_DIR)

    if not os.path.exists(DEPLOY_DIR):
        logging.info('create deploy dir..')
        os.makedirs(DEPLOY_DIR)

    cur_dir = os.getcwd()
    os.chdir(DEPLOY_DIR)
    subprocess.call("%(git)s init ." % dict(git=GIT))
    subprocess.call("%(git)s remote add origin %(github_url)s" % dict(git=GIT, github_url=config['github_url']))
    os.chdir(cur_dir)


def generate():

    copy_assets()

    logging.info('parsing all posts...')
    all_posts = []
    tags = defaultdict(list)
    categories = defaultdict(list)
    for post_path in [p for p in os.listdir(POSTS_DIR) if p.endswith('.markdown') or p.endswith('.md')]:
        post = read_post(post_path)
        if post['published']:
            all_posts.append(post)

            if post['categories']:
                for c in post['categories']:
                    categories[c].append(post)

            if post['tags']:
                for t in post['tags']:
                    tags[t].append(post)
        else:
            logging.debug('ignore private post: %s' % post['title'])

    logging.info('%d posts %d categories %d tags found' % (len(all_posts), len(categories), len(tags)))

    all_posts = sorted(all_posts, key=lambda p: p['path_parts'], reverse=True)

    post_count = len(all_posts)
    for i, post in enumerate(all_posts):
        previous = all_posts[i - 1] if i > 0 else None
        next = all_posts[i + 1] if i < post_count - 1 else None
        generate_post(post, previous, next)

    generate_pages(all_posts)
    generate_archives(all_posts)
    generate_tags(tags)
    generate_categories(categories)
    generate_feeds(all_posts[:config['post_per_feed']])
    generate_droppress_js(all_posts)


def clean():
    # should not delete .git folder
    if os.path.exists(DEPLOY_DIR):
        logging.info('cleanup deploy dir..')
        for f in os.listdir(DEPLOY_DIR):
            if f.startswith(".git"):
                continue
            path = os.path.join(DEPLOY_DIR, f)
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)


def deploy(commit_msg=None):
    if not commit_msg:
        commit_msg = "Site updated at %s" % datetime.now()

    cur_dir = os.getcwd()
    os.chdir(DEPLOY_DIR)
    add_cmd = '%(git)s add .' % dict(git=GIT)
    subprocess.call(add_cmd, shell=True)
    commit_cmd = '%(git)s commit -a -m "%(commit_msg)s"' % dict(git=GIT, commit_msg=commit_msg)
    subprocess.call(commit_cmd, shell=True)
    # NOTE: --force will overwrite remote origin
    push_cmd = "%(git)s push origin master --force" % dict(git=GIT)
    subprocess.call(push_cmd, shell=True)
    os.chdir(cur_dir)


def copy_assets():

    logging.info('copy assets..')
    assets_dir = os.path.join(DEPLOY_DIR, 'assets')
    shutil.copytree(ASSETS_DIR, assets_dir)

    # # bootstrap assets first
    # BOOTSTRAP_ASSETS = os.path.join('bootstrap', 'bootstrap')
    # shutil.copytree(BOOTSTRAP_ASSETS, assets_dir)

    # shutil.copy(os.path.join('bootstrap', 'docs', 'assets', 'js', 'jquery.js'), os.path.join(assets_dir, 'js'))

    # google_code_prettify_dir = os.path.join(assets_dir, 'js', 'google-code-prettify')
    # if not os.path.exists(google_code_prettify_dir):
    #     os.makedirs(google_code_prettify_dir)
    # shutil.copy(os.path.join('bootstrap', 'docs', 'assets', 'js', 'google-code-prettify', 'prettify.js'), google_code_prettify_dir)
    # shutil.copy(os.path.join('bootstrap', 'docs', 'assets', 'js', 'google-code-prettify', 'prettify.css'), google_code_prettify_dir)

    # # droppress assets last
    # for d in os.listdir(ASSETS_DIR):
    #     logging.debug('assets/%s' % (d))
    #     if d.startswith('.'):
    #         continue
    #     parent_dir = os.path.join(ASSETS_DIR, d)
    #     for f in os.listdir(parent_dir):
    #         src = os.path.join(ASSETS_DIR, d, f)
    #         dst = os.path.join(assets_dir, d)
    #         if not os.path.exists(dst):
    #             os.makedirs(dst)
    #         logging.debug('copy %s to %s' % (src, dst))
    #         shutil.copy(src, dst)

    # github requires CNAME file which contains custom domain name. ex: 'reiot.com'
    if config['cname']:
        open(os.path.join(DEPLOY_DIR, 'CNAME'), 'w').write(config['cname'])


_re_post = re.compile(r"(?P<year>\d\d\d\d)-(?P<month>\d\d)-(?P<day>\d\d)-(?P<slug>.+)\.(md|markdown)")
_re_jekyll_header_sep = re.compile(r'---\n')


def read_post(post_path):
    logging.debug('reading %s...' % post_path)

    m = _re_post.match(post_path)
    if not m:
        logging.warn('invalid post path: %s' % post_path)
        return

    year, month, day, slug = m.group('year'), m.group('month'), m.group('day'), m.group('slug')
    #logging.debug('year=%s month=%s day=%s slug=%s' % (year, month, day, slug))

    text = open(os.path.join(POSTS_DIR, post_path)).read()
    _, header, content = _re_jekyll_header_sep.split(text, 2)
    h = yaml.load(header)

    def to_markdown(content):
        try:
            return markdown.markdown(content, [
                'extra',    # footnote and else
                'nl2br',    # new line to break
                'tables',
            ])
        except:
            return None

    return dict(
        date='%s-%s-%s' % (year, month, day),
        path_parts=(year, month, day, slug),
        permlink='/%s/%s/%s/%s/' % (year, month, day, slug),
        title=h['title'],
        slug=slug,
        link=h.get('link'),
        categories=h.get('categories', []),
        tags=h.get('tags', []),
        published=h.get('published', False),
        comments=h.get('comments', False),
        created=h['date'],
        wordpress_id=h.get('wordpress_id'),
        excerpt=h.get('excerpt'),
        content=to_markdown(content),
    )

env = Environment(loader=PackageLoader('droppress', 'templates'))


def _gen_page(tmpl, args, parent_dir, filename='index.html'):
    template = env.get_template(tmpl)
    args.update(dict(app=APP_INFO, config=config))
    html = template.render(args)

    if not os.path.exists(parent_dir):
        os.makedirs(parent_dir)
    file_path = os.path.join(parent_dir, filename)
    open(file_path, "w").write(html)
    return file_path


def generate_post(post, prev=None, next=None):
    logging.debug('generate post: %s' % post['title'])

    yyyy, mm, dd, slug = post['path_parts']
    parent_dir = os.path.join(DEPLOY_DIR, str(yyyy), str(mm), str(dd), slug)
    _gen_page('post.html', dict(post=post), parent_dir)

    return True


def generate_pages(all_posts):
    logging.info('generate index.html and pages...')

    post_per_page = config['post_per_page']
    post_count = len(all_posts)
    all_pages = range(1, post_count / post_per_page + 2)
    max_page = all_pages[-1]

    page = 1
    for i in range(0, post_count, post_per_page):
        if page < PAGINATION_SIZE:
            pagination = all_pages[:PAGINATION_SIZE]
        elif page > max_page - PAGINATION_SIZE:
            pagination = all_pages[max_page - PAGINATION_SIZE:]
        else:
            pagination = all_pages[page - PAGINATION_SIZE / 2:page + PAGINATION_SIZE / 2]

        parent_dir = DEPLOY_DIR if page == 1 else os.path.join(DEPLOY_DIR, "page", str(page))
        args = dict(
            posts=all_posts[i:i + post_per_page],
            page=page,
            max_page=max_page,
            pagination=pagination,
        )
        _gen_page('index.html', args, parent_dir)

        page += 1


def generate_archives(all_posts):
    logging.info('generate archives...')

    post_counter = Counter()
    archives = {}
    for post in all_posts:
        yyyy, mm, dd, slug = post['path_parts']
        by_year = archives.setdefault(yyyy, {})
        by_month = by_year.setdefault(mm, {})
        by_day = by_month.setdefault(dd, [])
        by_day.append(post)

        post_counter[yyyy] += 1

    # for year, by_month in archives.items():
    #     logging.info("%s: %d"%(year, len(by_month)))
    #     for month, by_day in by_month.items():
    #         logging.info('\t%s: %d'%(month, len(by_day)))
    #         for day, _posts in by_day.items():
    #             logging.info('\t\t%s: %d'%(day, len(_posts)))
    #             for post in _posts:
    #                 logging.info('\t\t\t%s'%post['title'])

    args = dict(
        archives=archives,
        post_counter=post_counter,
        all_posts=all_posts,
    )
    _gen_page('archives.html', args, os.path.join(DEPLOY_DIR, 'archives'))


def generate_tags(tags):
    logging.info('generate tags...')

    _gen_page('tags.html', dict(tags=tags), os.path.join(DEPLOY_DIR, 'tag'))

    for tag, posts in tags.items():
        _gen_page('tag.html', dict(tag=tag, posts=posts), os.path.join(DEPLOY_DIR, 'tag', tag))


def generate_categories(categories):
    logging.info('generate categories...')

    _gen_page('categories.html', dict(categories=categories), os.path.join(DEPLOY_DIR, 'category'))

    for category, posts in categories.items():
        _gen_page('category.html', dict(category=category, posts=posts), os.path.join(DEPLOY_DIR, 'category', category))


def generate_feeds(posts):
    logging.info('generate feeds...')

    feed = feedgenerator.Atom1Feed(
        title=config['title'],
        link=config['url'],
        description=config['description'],
        author_name=config['author_name'],
        language=config['language'],
        feed_url=config['feed_url'],
    )

    for post in posts:
        pubdate = post['created']
        if not isinstance(pubdate, datetime):
            fmt = '%Y-%m-%d %H:%M:%S'
            if len(pubdate) == 16:
                fmt = fmt[:-3]
            pubdate = datetime.strptime(pubdate, fmt)

        #logging.info('title=%s date=`%s`(%s)' % (post['title'], pubdate, type(pubdate)))

        feed.add_item(
            title=post['title'],
            link=post['permlink'],
            pubdate=pubdate,
            description=post['content'],
        )

    open(os.path.join(DEPLOY_DIR, 'atom.xml'), 'w').write(feed.writeString('UTF-8'))


def generate_droppress_js(all_posts):
    # title search using typeahead
    titles = dict([(post['title'], post['permlink']) for post in all_posts])
    args = dict(
        all_posts=json.dumps(titles, indent=2),
    )
    parent_dir = os.path.join(DEPLOY_DIR, 'assets', 'js')
    _gen_page('droppress.js', args, parent_dir, 'droppress.js')


def run_server():
    rel_deploy_dir = os.path.relpath(DEPLOY_DIR, os.getcwd())
    cmd = "%(locally)s -d -w %(deploy_dir)s" % dict(locally=LOCALLY, deploy_dir=rel_deploy_dir)
    subprocess.call(cmd, shell=True)


def new_post(slug='draft'):
    now = datetime.now()

    filename = '%s-%s.markdown' % (now.date().strftime('%Y-%m-%d'), slug)
    logging.info('new post: %s' % filename)

    args = dict(
        slug=slug,
        now=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        default_category=config['default_category'],
    )
    post_file = _gen_page('new_post.markdown', args, POSTS_DIR, filename)

    # launch editor
    if EDITOR:
        cmd = "%s %s" % (EDITOR, post_file)
        subprocess.call(cmd, shell=True)

if __name__ == '__main__':
    import argparse
    import subprocess
    parser = argparse.ArgumentParser()
    parser.add_argument('action', nargs='?', metavar='ACTION', type=str, default='generate', choices=ACTIONS)
    parser.add_argument('-v', '--verbose', action='store_true', default=False)
    parser.add_argument('-m', '--commit-msg', metavar='COMMIT_MSG', type=str, default='')
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.action == 'clean':
        clean()
    elif args.action == 'generate':
        clean()
        generate()
    elif args.action == 'run':
        run_server()
    elif args.action == 'deploy':
        deploy(commit_msg=args.commit_msg)
    elif args.action == 'new_post':
        new_post()
