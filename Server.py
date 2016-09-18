#!/usr/bin/env python
# -*- encoding: utf-8 -*-
import httplib
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

	def func_categorys(self, path, data):
		parent_id = int(data.get('p', 0))
		taxonomy = data.get('tax', 'category')

		offset = data.get('offset', 0)
		limit = data.get('max', 20)

		db = self.database.connect()
		try:
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
			self.response_json({
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
			})

			rs.close()

		finally:
			db.close()

	def func_post(self, path, data):
		pass

	def func_posts(self, path, data):
		taxonomy = data.get('tax', 'post')
		category = data.get('c', None)

		offset = data.get('offset', 0)
		limit = data.get('max', 20)

		db = self.database.connect()
		try:
			q = []
			sql = """SELECT `wp_posts`.`ID`, `wp_posts`.`post_date`,`wp_posts`.`post_title`,`wp_posts`.`post_content` FROM `wp_posts`"""
			sql += " WHERE `wp_posts`.`post_type` =%s AND `wp_posts`.`post_status`='publish'"
			q.append(taxonomy)

			if category:
				sql = """SELECT `wp_posts`.`ID`, `wp_posts`.`post_date`,`wp_posts`.`post_title`,`wp_posts`.`post_content` FROM `wp_term_relationships` INNER JOIN `wp_posts` ON `wp_posts`.`ID` = `wp_term_relationships`.`object_id`"""
				sql += " WHERE `wp_posts`.`post_type` =%s AND `wp_posts`.`post_status`='publish' AND `wp_term_relationships`.`term_taxonomy_id` = %s"
				q.append(category)

			sql += " ORDER BY `wp_posts`.`post_date` DESC"
			sql += " LIMIT %s,%s"
			q.append(offset)
			q.append(limit)

			rs = db.execute(sql, *q)

			def post_categorys(post_id):
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

			def post_meta(post_id):
				sql = "SELECT `meta_key`,`meta_value` FROM `wp_postmeta` WHERE post_id=%s"
				rs = db.execute(sql, post_id)
				return dict((x['meta_key'], x['meta_value']) for x in rs if not x['meta_key'].startswith('_'))

			def post_attachment(post_id):
				sql = "SELECT `id`, `post_date`,`post_title`,`guid` as `url`, `post_mime_type` as `mime_type` FROM `wp_posts`"
				sql += " WHERE `post_type`='attachment' AND post_parent=%s"
				rs = db.execute(sql, post_id)
				return [{
					        'id': x['id'],
					        'date': x['post_date'],
					        'title': x['post_date'],
					        'mime_type': x['mime_type'],
					        'url': x['url'],
				        } for x in rs]

			self.response_json({
				'offset': offset,
				'max': limit,
				'tax': taxonomy,
				'data': [{
					         'id': x['id'],
					         'data': x['post_date'],
					         'title': x['post_title'],
					         'content': x['post_content'],
					         'category': post_categorys(x['id']),
					         'meta': post_meta(x['id']),
					         'attachment': post_attachment(x['id']),
				         } for x in rs]
			})

			rs.close()

		finally:
			db.close()


if __name__ == "__main__":
	settings = ConfigParser()
	settings.read('settings.ini')

	engine = create_engine(settings.get('default', 'db_uri'), echo=True, case_sensitive=False, convert_unicode=True,
	                       echo_pool=True)

	application = tornado.web.Application([
		(r"/(.*)", MainHandler, dict(database=engine)),
	])
	application.listen(8888)
	tornado.ioloop.IOLoop.current().start()
