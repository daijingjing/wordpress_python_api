#!/usr/bin/env python
# -*- encoding: utf-8 -*-
import httplib
import io
import json
import logging
import traceback
from datetime import datetime, date

import dateutil.tz
import tornado.ioloop
import tornado.web
from ConfigParser import ConfigParser

from decimal import Decimal
from sqlalchemy import create_engine


class JsonDumper(json.JSONEncoder):
	def default(self, obj):
		if isinstance(obj, datetime):
			return obj.replace(tzinfo=dateutil.tz.tzlocal()).strftime('%Y-%m-%dT%H:%M:%SZ%z')
		elif isinstance(obj, date):
			return obj.replace(tzinfo=dateutil.tz.tzlocal()).strftime('%Y-%m-%d')
		elif isinstance(obj, Decimal):
			return str(obj)
		else:
			return json.JSONEncoder.default(self, obj)


def json_dumps(data):
	return json.dumps(data, cls=JsonDumper, sort_keys=False)


def post_categorys(db, post_id):
	sql = "SELECT `wp_term_taxonomy`.`taxonomy`,`wp_terms`.`term_id`,`wp_terms`.`name`,`wp_terms`.`slug`,`wp_term_taxonomy`.`parent` AS `parent_id`,b.`name` AS `parent_name`,b.`slug` as `parent_slug`,`wp_options`.`option_value` AS `poster` FROM `wp_term_relationships` INNER JOIN `wp_term_taxonomy` ON `wp_term_taxonomy`.`term_taxonomy_id` = `wp_term_relationships`.`term_taxonomy_id` INNER JOIN `wp_terms` ON `wp_term_taxonomy`.`term_id`=`wp_terms`.`term_id` LEFT JOIN `wp_terms` b ON b.term_id = `wp_term_taxonomy`.`parent` LEFT JOIN `wp_options` ON `wp_options`.`option_name` = CONCAT('z_taxonomy_image', `wp_terms`.`term_id`)"
	sql += " WHERE `wp_term_relationships`.`object_id` = %s"

	rs = db.execute(sql, post_id)

	return [{
		        'id': x['term_id'],
		        'name': x['name'],
		        'slug': x['slug'],
		        'poster': x['poster'],
		        'parent': {
			        'id': x['parent_id'],
			        'name': x['parent_name'],
			        'slug': x['parent_slug'],
		        } if x['parent_id'] and x['parent_name'] and x['parent_slug'] else None,
	        } for x in rs]


def post_meta(db, post_id):
	sql = "SELECT `meta_key`,`meta_value` FROM `wp_postmeta` WHERE post_id=%s"

	rs = db.execute(sql, post_id)

	return dict((x['meta_key'], x['meta_value']) for x in rs if not x['meta_key'].startswith('_'))


def post_attachment(db, post_id):
	sql = "SELECT `id`, `post_date`,`post_title`,`guid` as `url`, `post_mime_type` as `mime_type` FROM `wp_posts`"
	sql += " WHERE `post_type`='attachment' AND post_parent=%s"

	rs = db.execute(sql, post_id)

	return dict((x['id'], {
		'date': x['post_date'],
		'title': x['post_date'],
		'mime_type': x['mime_type'],
		'url': x['url'],
	}) for x in rs)


def category_parents(db, category_id):
	parent = []
	p = db.execute('SELECT `parent` FROM `wp_term_taxonomy` WHERE `term_id`=%s', category_id).scalar()
	if p:
		parent.append(p)
		parent += category_parents(db, p)

	return parent


def category_childrens(db, category_id):
	parent = []
	childrens = db.execute('SELECT `term_id` FROM `wp_term_taxonomy` WHERE `parent`=%s', category_id).fetchall()
	parent += [x['term_id'] for x in childrens]
	for p in parent:
		parent += category_childrens(db, p)

	return parent


def query_category(db, category_id):
	sql = """SELECT `wp_term_taxonomy`.`taxonomy`,`wp_terms`.`term_id`,`wp_terms`.`name`,`wp_terms`.`slug`,`wp_term_taxonomy`.`parent` AS `parent_id`,b.`name` AS `parent_name`,b.`slug` as `parent_slug`,`wp_options`.`option_value` AS `poster` FROM `wp_term_taxonomy` INNER JOIN `wp_terms` ON `wp_term_taxonomy`.`term_id`=`wp_terms`.`term_id` LEFT JOIN `wp_terms` b ON b.term_id = `wp_term_taxonomy`.`parent` LEFT JOIN `wp_options` ON `wp_options`.`option_name` = CONCAT('z_taxonomy_image', `wp_terms`.`term_id`)"""
	sql += " WHERE `wp_terms`.`term_id`=%s"

	x = db.execute(sql, category_id).first()

	return {
		'id': x['term_id'],
		'name': x['name'],
		'slug': x['slug'],
		'poster': x['poster'],
		'parent': query_category(db, x['parent_id']) if x['parent_id'] else None,
	} if x else None


def query_categorys(db, taxonomy, parent_id, offset, limit):
	q = []
	sql = """SELECT `wp_term_taxonomy`.`taxonomy`,`wp_terms`.`term_id`,`wp_terms`.`name`,`wp_terms`.`slug`,`wp_term_taxonomy`.`parent` AS `parent_id`,b.`name` AS `parent_name`,b.`slug` as `parent_slug`,`wp_options`.`option_value` AS `poster` FROM `wp_term_taxonomy` INNER JOIN `wp_terms` ON `wp_term_taxonomy`.`term_id`=`wp_terms`.`term_id` LEFT JOIN `wp_terms` b ON b.term_id = `wp_term_taxonomy`.`parent` LEFT JOIN `wp_options` ON `wp_options`.`option_name` = CONCAT('z_taxonomy_image', `wp_terms`.`term_id`)"""
	sql += " WHERE `wp_terms`.`slug` != 'uncategorized' AND `wp_term_taxonomy`.`parent`=%s"
	q.append(parent_id)

	if taxonomy:
		sql += " AND `wp_term_taxonomy`.`taxonomy`=%s"
		q.append(taxonomy)

	sql += " ORDER BY `wp_terms`.`term_order`"
	sql += " LIMIT %s,%s"
	q.append(offset)
	q.append(limit)

	rs = db.execute(sql, *q)

	results = {
		'offset': offset,
		'max': limit,
		'tax': taxonomy,
		'parent_id': parent_id,
		'data': [{
			         'id': x['term_id'],
			         'name': x['name'],
			         'slug': x['slug'],
			         'poster': x['poster'],
			         'parent': {
				         'id': x['parent_id'],
				         'name': x['parent_name'],
				         'slug': x['parent_slug'],
			         } if x['parent_id'] and x['parent_name'] and x['parent_slug'] else None,
		         } for x in rs]
	}
	rs.close()
	return results


def query_post(db, post_id):
	sql = """SELECT `wp_posts`.`ID` as `id`, `wp_posts`.`post_date`,`wp_posts`.`post_title`,`wp_posts`.`post_content` FROM `wp_posts`"""
	sql += " WHERE `wp_posts`.`ID`=%s AND `wp_posts`.`post_status`='publish'"

	x = db.execute(sql, post_id).first()

	return {
		'id': x['id'],
		'data': x['post_date'],
		'title': x['post_title'],
		'content': x['post_content'],
		'category': post_categorys(db, x['id']),
		'meta': post_meta(db, x['id']),
		'attachment': post_attachment(db, x['id']),
	} if x else None


def query_posts(db, taxonomy, category, offset, limit):
	q = []
	sql = """SELECT `wp_posts`.`ID`, `wp_posts`.`post_date`,`wp_posts`.`post_title`,`wp_posts`.`post_content` FROM `wp_posts`"""
	sql += " WHERE `wp_posts`.`post_type` =%s AND `wp_posts`.`post_status`='publish'"
	q.append(taxonomy)

	if category:
		categorys = category_childrens(db, category)
		categorys.append(category)

		sql = """SELECT `wp_posts`.`ID`, `wp_posts`.`post_date`,`wp_posts`.`post_title`,`wp_posts`.`post_content` FROM `wp_term_relationships` INNER JOIN `wp_posts` ON `wp_posts`.`ID` = `wp_term_relationships`.`object_id`"""
		sql += " WHERE `wp_posts`.`post_type` =%s AND `wp_posts`.`post_status`='publish'"
		sql += " AND `wp_term_relationships`.`term_taxonomy_id` IN (%s)" % ','.join(map(lambda x: '%s', categorys))

		q += categorys

	sql += " ORDER BY `wp_posts`.`post_date` DESC"
	sql += " LIMIT %s,%s"
	q.append(offset)
	q.append(limit)

	rs = db.execute(sql, *q)

	results = {
		'offset': offset,
		'max': limit,
		'tax': taxonomy,
		'category': query_category(db, category) if category else None,
		'data': [{
			         'id': x['id'],
			         'data': x['post_date'],
			         'title': x['post_title'],
			         'content': x['post_content'],
			         'category': post_categorys(db, x['id']),
			         'meta': post_meta(db, x['id']),
			         'attachment': post_attachment(db, x['id']),
		         } for x in rs]
	}
	rs.close()

	return results


class MainHandler(tornado.web.RequestHandler):
	def initialize(self, database):
		self.database = database

	def get(self, p):
		if not p:
			logging.error("功能调用错误，未提供调用方法")
			raise tornado.web.HTTPError(404, "功能调用错误，未提供调用方法")

		params = str(p).split('/') if p else []
		attr = getattr(self, 'func_' + params[0], None)

		if not attr:
			logging.error("功能方法不存在(%s)" % (str(p)))
			raise tornado.web.HTTPError(404, "功能方法不存在(%s)" % (str(p)))

		try:
			args = {}
			for k in self.request.arguments.keys():
				args[k] = self.get_argument(k)
			attr(params[1:], args)

		except tornado.web.HTTPError, e:
			traceback.print_exc()
			logging.error("服务器内部功能调用错误(URI: %s, Error: %s, Content: %s)" % (str(p), str(e), str(self.request.body)))
			raise

		except BaseException, e:
			traceback.print_exc()
			logging.error("服务器内部功能调用错误(URI: %s, Error: %s, Content: %s)" % (str(p), str(e), str(self.request.body)))
			raise

	def set_default_headers(self):
		self.set_header('Server', 'Wordpress-API-Server')

	def response_json(self, data):
		self.set_header('Content-Type', 'application/json; charset=utf-8')
		self.write(json_dumps(data))
		self.write('\n')

	def write_error(self, status_code, **kwargs):
		logging.error(u'Error Request Url: ' + unicode(self.request.path))
		logging.error(u'Error Request Body: ' + unicode(self.request.body if self.request.body else ''))
		data = {'error': status_code, 'message': httplib.responses[status_code]}

		for item in kwargs['exc_info']:
			if isinstance(item, tornado.web.HTTPError):
				data['message'] = item.log_message
			elif isinstance(item, Exception):
				data['message'] = str(item)

		self.response_json(data)

	def func_category(self, path, data):
		if not path:
			raise tornado.web.HTTPError(404, "方法调用错误,未提供分类ID")

		db = self.database.connect()
		try:
			results = query_category(db, path)
			if not results:
				raise tornado.web.HTTPError(404, "分类信息不存在(%s)" % (str(path)))

			self.response_json(results)

		finally:
			db.close()

	def func_categorys(self, path, data):
		parent_id = int(data.get('p', 0))
		taxonomy = data.get('tax', 'category')

		offset = max(0, int(data.get('offset', 0)))
		limit = min(100, int(data.get('max', 20)))

		db = self.database.connect()
		try:
			results = query_categorys(db, taxonomy, parent_id, offset, limit)

			self.response_json(results)

		finally:
			db.close()

	def func_post(self, path, data):
		if not path:
			raise tornado.web.HTTPError(404, "方法调用错误,未提供文章ID")

		db = self.database.connect()
		try:
			results = query_post(db, path)
			if not results:
				raise tornado.web.HTTPError(404, "文章不存在(%s)" % (str(path)))

			self.response_json(results)

		finally:
			db.close()

	def func_posts(self, path, data):
		taxonomy = data.get('tax', 'post')
		category = data.get('c', None)

		offset = max(0, int(data.get('offset', 0)))
		limit = min(100, int(data.get('max', 20)))

		db = self.database.connect()
		try:
			results = query_posts(db, taxonomy, category, offset, limit)
			self.response_json(results)

		finally:
			db.close()

	def func_icon(self, path, data):
		from PIL import Image
		from PIL import ImageDraw
		from PIL import ImageFont

		text = data.get('txt', u'测')
		if not isinstance(text, unicode):
			text = unicode(text)

		font_size = data.get('fontsize', 100)
		image_size = (int(data.get('s', 200)), int(data.get('s', 200)))
		background_color = (200, 200, 200)
		text_color = (0, 0, 0)

		font = ImageFont.truetype('AppleGothic.ttf', font_size)
		im = Image.new("RGBA", image_size, background_color)
		text_size = font.getsize(text)

		draw = ImageDraw.Draw(im)
		draw.text(((image_size[0] - text_size[0]) / 2, (image_size[1] - text_size[1]) / 2), text,
		          text_color, font=font)
		del draw

		o = io.BytesIO()
		im.save(o, format="PNG")

		s = o.getvalue()
		self.set_header('Content-type', 'image/png')
		self.set_header('Content-length', len(s))
		self.write(s)
		self.finish()


if __name__ == "__main__":
	settings = ConfigParser()
	settings.read('settings.ini')

	engine = create_engine(settings.get('default', 'db_uri'), echo=False, case_sensitive=False, convert_unicode=True,
	                       echo_pool=True)

	application = tornado.web.Application([
		(r"/(.*)", MainHandler, dict(database=engine)),
	])
	application.listen(8888)
	tornado.ioloop.IOLoop.current().start()
