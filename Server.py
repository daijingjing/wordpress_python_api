#!/usr/bin/env python
# -*- encoding: utf-8 -*-

import tornado.ioloop
import tornado.web


def get_category():
    sql = "SELECT `wp_term_taxonomy`.`taxonomy`,`wp_term_taxonomy`.`parent`,`wp_terms`.* FROM `wp_term_taxonomy`,`wp_terms` WHERE `wp_term_taxonomy`.`term_id`=`wp_terms`.`term_id` AND `wp_term_taxonomy`.`parent`=%s ORDER BY `wp_terms`.`term_order`"


class MainHandler(tornado.web.RequestHandler):
    def get(self):
        self.write("Hello, world")

if __name__ == "__main__":
    application = tornado.web.Application([
        (r"/", MainHandler),
    ])
    application.listen(8888)
    tornado.ioloop.IOLoop.current().start()

