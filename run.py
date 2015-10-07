import asyncio
from pprint import pprint
import json
import logging
import os

import aiohttp
import websockets

log = logging.getLogger(__name__)

class SlackError(Exception):
    pass

class SlackBot(object):
    def __init__(self, token, url='https://slack.com/api/'):
        self.token = token
        self.params = {'token': token}
        self.url = url
        self.ws_url = None
        self.channel_names = {} # channel or group id to names
        self.user_names = {}
        self.bot_id = None
        self.bot_name = None

    def _upsert_user(self, user):
        self.user_names[user['id']] = user['name']

    def _upsert_channel(self, channel):
        self.channel_names[channel['id']] = channel['name']

    def _init_login_data(self, d):
        about_me = d['self']
        self.bot_id = about_me['id']
        self.bot_name = about_me['name']

        for u in d.get('bots', []):
            self._upsert_user(u)

        for u in d.get('users', []):
            self._upsert_user(u)

        for c in d.get('channels', []):
            self._upsert_channel(c)

        for c in d.get('groups', []):
            self._upsert_channel(c)
            
    def _calculate_prefix(self, msg):
        if msg['channel'].startswith('D'): #don't want to address in direct message
            return ''

        prefix = self.user_names.get(msg['user'], '')
        if prefix:
            prefix = prefix + ', '
        return prefix

    @asyncio.coroutine
    def _fetch(self, cmd):
        url = self.url + cmd
        resp = yield from aiohttp.request('GET', url, params=self.params)
        return (yield from resp.json())

    @asyncio.coroutine
    def start(self):
        _id = 1
        d = yield from self._fetch('rtm.start')
        if not d['ok']:
            raise SlackError(d.get('error'))
        self._init_login_data(d)
        log.debug(d)
        log.info('Channels: %s', ', '.join(self.channel_names.values()))
        log.info('Users: %s', ', '.join(self.user_names.values()))

        self.ws_url = d['url']
        ws = yield from websockets.connect(self.ws_url)
        while True:
            msg = yield from ws.recv()
            msg = json.loads(msg)
            log.debug('Recieved %s', msg)
            msg_type = msg.get('type')
            if msg_type == 'message':
                channel = msg['channel']
                user_id = msg['user']
                if user_id != self.bot_id:
                    prefix = self._calculate_prefix(msg)
                    response = {'id': _id, 'type': 'message', 'channel': channel, 'text': '{}hello'.format(prefix)}
                    log.info('Sending %s', response)
                    yield from ws.send(json.dumps(response))
                    _id += 1
            elif msg_type == 'channel_joined' or msg_type == 'group_joined':
                self._upsert_channel(msg['channel'])
                log.info('Channels: %s', ', '.join(self.channel_names.values()))


def configure_logging(log):
    log_level = logging.DEBUG
    formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
    handler = logging.StreamHandler()
    handler.setLevel(log_level)
    handler.setFormatter(formatter)
    log.setLevel(log_level)
    log.addHandler(handler)

bot = SlackBot(os.environ.get('SLACK_TOKEN'))
if __name__ == '__main__':
    configure_logging(log)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(bot.start())

