import os
import asyncio

from botslacks import SlackBot, log, configure_logging
from botslacks.commands.jenkins import Jenkins

bot = SlackBot(os.environ.get('SLACK_TOKEN'))

if __name__ == '__main__':
    configure_logging(log)

    
    j = Jenkins(
            url=os.environ.get('JENKINS_URL'), 
            auth=(os.environ.get('JENKINS_USERNAME'), os.environ.get('JENKINS_TOKEN')))
    bot.register_command('.jenkins', j.process)

    loop = asyncio.get_event_loop()
    loop.run_until_complete(j.init())
    loop.run_until_complete(bot.start())

