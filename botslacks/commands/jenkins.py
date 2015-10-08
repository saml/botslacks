import asyncio
import re
from collections import namedtuple
import operator

import aiohttp

from botslacks import log, parse_args, SubCommand, help_message

NON_WORD = re.compile(r'[\d\W]+')

JenkinsJob = namedtuple('JenkinsJob', ['name', 'url'])


def parse_jobs(jobs):
    '''[{name:..., url:...}, ...] => {key: JenkinsJob}'''
    d = {}
    for job in jobs:
        name = job['name']
        job_url = job['url']
        key = NON_WORD.sub('', name.lower())
        d[key] = JenkinsJob(name, job_url)
    return d
    

class Jenkins(object):

    def __init__(self, url, auth):
        '''
        url is jenkins base url.
        auth is (username,token).
        '''
        self.url = url
        username,password = auth
        self.auth = aiohttp.BasicAuth(username, password)
        self.http = aiohttp.ClientSession(auth=self.auth)
        self.jobs = {}
        self.subcommands = {
            'info': SubCommand('<project name>', 'displays project information.', self.info),
            'help': SubCommand('', 'displays this message.', self.help),
        }
        self.argspec = '|'.join(self.subcommands.keys())
    
    

    @asyncio.coroutine
    def init(self):
        yield from self.reload_jobs()

    @asyncio.coroutine
    def reload_jobs(self):
        self.jobs = yield from self.fetch_all_jobs()
        return self.jobs

    def find_job(self, s):
        words = s.lower().split()
        scores = {k:0 for k in self.jobs.keys()}
        for word in words:
            for k,score in scores.items():
                if word in k:
                    scores[k] += 1
        l = sorted(scores.items(), key = operator.itemgetter(1), reverse=True)
        if l:
            top_match = l[0]
            key,score = top_match
            log.info('Found %s from input "%s"', key, s)
            return self.jobs[key]


    @asyncio.coroutine
    def fetch_all_jobs(self):
        url = self.url + '/api/json'
        r = yield from self.http.get(url)
        d = yield from r.json()
        return parse_jobs(d['jobs'])

    def info(self, text):
        if text:
            job = self.find_job(text)
            if job:
                return 'Found {} ({})'.format(job.name, job.url)

    def help(self, text):
        return 'Available subcommands ' + help_message(self.subcommands)
        
    def process(self, text):
        command,args = parse_args(text)
        subcommand = self.subcommands.get(command)
        if subcommand:
            return subcommand.func(args)

