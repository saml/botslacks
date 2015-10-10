import asyncio
import logging
import json
from collections import namedtuple

import aiohttp
import websockets

log = logging.getLogger(__name__)


class BotCommand(object):
    def __init__(self, func, description=None, argspec=None, key=None, subcommands=None):
        '''
        func is str -> str
        subcommands is CommandDispatcher
        '''
        self.func = func
        self.description = description
        self.key = key
        self.subcommands = subcommands
        # automatically caclulate argspec from subcommands if argspec is not supplied.
        self.argspec = '|'.join(subcommands.keys()) if subcommands and not argspec else argspec

    def __call__(self, input_text):
        return self.func(input_text)



class CommandDispatcher(object):
    '''Can register new commands and dispatch.'''
    def __init__(self):
        self._commands = {}

        # for display help
        self.command_width = 0
        self.argspec_width = 0

    def register_command(self, key, func, argspec='', description='', subcommands=None):
        if key in self._commands:
            raise SlackError('Already registered: {}'.format(key))
        self._commands[key] = BotCommand(func, key=key, description=description, argspec=argspec, subcommands=subcommands)
        
        command_length = len(key)
        if command_length > self.command_width:
            self.command_width = command_length
        argspec_length = len(argspec)
        if argspec_length > self.argspec_width:
            self.argspec_width = argspec_length

    def has(self, key):
        return key in self._commands

    def get(self, key):
        return self._commands.get(key)

    def keys(self):
        return self._commands.keys()

    def __iter__(self):
        '''iterate all registered commands'''
        return self._commands.items()

    def help(self, parent_command=None):
        texts = []

        prefix = ''
        argspec_width = self.argspec_width
        command_width = self.command_width

        if parent_command:
            prefix = parent_command.key + ' '
            argspec_width = max(len(parent_command.argspec), self.argspec_width)
            command_width = len(prefix) + self.command_width

            texts.append('{} {} {}'.format(
                parent_command.key.rjust(command_width), 
                parent_command.argspec.rjust(argspec_width),
                parent_command.description))

        for command in self._commands.values():
            texts.append('{} {} {}'.format(
                (prefix + command.key).rjust(command_width),
                command.argspec.rjust(argspec_width),
                command.description))
        return '\n'.join(texts)

def configure_logging(log_level=logging.INFO):
    '''default logging configuration'''
    if len(log.handlers) == 0:
        formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
        handler = logging.StreamHandler()
        handler.setLevel(log_level)
        handler.setFormatter(formatter)
        log.setLevel(log_level)
        log.addHandler(handler)

def parse_args(s):
    '''
    'foo bar a b c' => ('foo', 'bar a b c')
    'foo' => ('foo', '')
    '''
    splitted = s.split(maxsplit=1)
    if len(splitted) >= 2:
        return splitted[0],splitted[1]
    if len(splitted) == 1:
        return splitted[0],''
    return '',''

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
        self.commands = CommandDispatcher()

    def register_command(self, key, func, argspec='', description='', subcommands=None):
        '''subcommands is CommandDispatcher'''
        self.commands.register_command(key, func, argspec, description, subcommands)

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
        d = yield from self._fetch('rtm.start')
        if not d['ok']:
            raise SlackError(d.get('error'))
        self._init_login_data(d)
        log.debug(d)
        log.info('Channels: %s', ', '.join(self.channel_names.values()))
        log.info('Users: %s', ', '.join(self.user_names.values()))

        self.ws_url = d['url']
        ws = yield from websockets.connect(self.ws_url)
        response_id = 1
        while True:
            msg = yield from ws.recv()
            msg = json.loads(msg)
            log.debug('Recieved %s', msg)
            msg_type = msg.get('type')
            if msg_type == 'message':
                user_id = msg['user']
                if user_id != self.bot_id:
                    response = self._calculate_response(msg, response_id)
                    if response:
                        log.info('Sending %s', response)
                        yield from ws.send(json.dumps(response))
                        response_id += 1
            elif msg_type == 'channel_joined' or msg_type == 'group_joined':
                self._upsert_channel(msg['channel'])
                log.info('Channels: %s', ', '.join(self.channel_names.values()))

    def _calculate_response(self, msg, response_id):
        input_text = msg['text']
        key,args_text = parse_args(input_text)
        command = self.commands.get(key)
        if command is not None:
            response_text = command(args_text)
            if response_text:
                prefix = self._calculate_prefix(msg)
                return {'id': response_id, 'type': 'message', 'channel': msg['channel'], 'text': prefix + response_text}


# An example command
class Help(object):
    def __init__(self, bot):
        self.commands = bot.commands

    def _help_text(self, command):
        return '{} {} {}'.format(command.key, command.argspec, command.description)

    def __call__(self, text=''):
        command = self.commands.get(text)
        help_text = ''
        if command:
            if command.subcommands:
                help_text = command.subcommands.help(command)
            else:
                help_text = self._help_text(command)
        else:
            help_text = self.commands.help()
        return '```{}```'.format(help_text)
