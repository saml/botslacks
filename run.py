import os
import asyncio

from botslacks import SlackBot, log, configure_logging, Help
from botslacks.commands.jenkins import Jenkins

bot = SlackBot(os.environ.get('SLACK_TOKEN'))

def ping_command(text):
    if text.lower() == 'pong':
        return 'You responded yourself.'
    return 'pong'

if __name__ == '__main__':
    configure_logging(log)

    
    j = Jenkins(
            url=os.environ.get('JENKINS_URL'), 
            auth=(os.environ.get('JENKINS_USERNAME'), os.environ.get('JENKINS_TOKEN')))
    bot_help = Help(bot)

    bot.register_command('.ping', ping_command, '[pong]', 'checks if bot is alive.')
    bot.register_command('.jenkins', j.process, j.argspec, subcommands=j.subcommands) 
    bot.register_command('.help', bot_help, bot_help.argspec, bot_help('.help'))

    loop = asyncio.get_event_loop()
    loop.run_until_complete(j.init())
    loop.run_until_complete(bot.start())

