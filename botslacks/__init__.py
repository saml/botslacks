import asyncio
import logging
import json
from collections import namedtuple

import aiohttp
import websockets

log = logging.getLogger(__name__)

SubCommand = namedtuple('SubCommand', ['argspec', 'help', 'func', 'subcommands'])
SubCommand.__new__.__defaults__ = (None, None, None, None)



def _find_widths(commands):
    command_width = 0
    argspec_width = 0
    for command,subcommand in commands.items():
        command_length = len(command)
        argspec_length = len(subcommand.argspec)
        if command_length > command_width:
            command_width = command_length
        if argspec_length > argspec_width:
            argspec_width = argspec_length

    return command_width,argspec_width

def help_message(commands):
    '''Given dict of command (str) to SubCommand, returns help string.'''
    command_width,argspec_width = _find_widths(commands)
    msg = []
    for command,subcommand in commands.items():
        msg.append('{} {} -- {}'.format(command.rjust(command_width), subcommand.argspec.rjust(argspec_width), subcommand.help))
    return '''```{}```'''.format('\n'.join(msg))

def configure_logging(log):
    '''default logging configuration'''
    if len(log.handlers) == 0:
        log_level = logging.DEBUG
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
        self.command_handlers = {}

    def register_command(self, command, func, argspec='', help_text='', subcommands=None):
        if command in self.command_handlers:
            raise SlackError('Already registered: {}'.format(command))
        self.command_handlers[command] = SubCommand('', help_text, func, subcommands)

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
        command,args = parse_args(input_text)
        subcommand = self.command_handlers.get(command)
        if subcommand is not None:
            response_text = subcommand.func(args)
            if response_text:
                prefix = self._calculate_prefix(msg)
                return {'id': response_id, 'type': 'message', 'channel': msg['channel'], 'text': prefix + response_text}

    def help(self, text):
        return help_message(self.command_handlers)


# An example command
class Help(object):
    def __init__(self, bot):
        self.commands = bot.command_handlers
        self.argspec = '[any command]'


    def __call__(self, text=''):
        if text in self.commands:
            command = text
            c = self.commands[command]
            if c.subcommands:
                return help_message({'{} {}'.format(command, k):v for k,v in c.subcommands.items()})
        log.info('asdf %s', text)
        return help_message({'{} {}'.format(text, k):v for k,v in self.commands.items()})
