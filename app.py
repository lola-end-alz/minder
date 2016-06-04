import logging
import json
import flask
import httplib2
from flask import Flask, jsonify, request

from config import Config
from log import configure
from sms import send_sms
from db import db

from rq import Queue
from rq.job import Job
from worker import conn

from apiclient import discovery
from oauth2client import client

q = Queue(connection=conn)

configure(Config.ENV)
app = Flask('minder')
logger = logging.getLogger('minder')


@app.before_request
def log_request():
    logger.info('{} {}'.format(request.method, request.path))


def _get_echo_response(speech_output, card_output, reprompt_message):
    return {
        'version': '1.0',
        'response': {
            'outputSpeech': {
                'type': 'PlainText',
                'text': speech_output
            },
            'card': {
                'type': 'Simple',
                'title': 'Minder',
                'content': card_output
            },
            'reprompt': {
                'outputSpeech': {
                    'type': 'PlainText',
                    'text': reprompt_message
                }
            },
            'shouldEndSession': False
        },
        'sessionAttributes': {'source': 'minder'}
    }


@app.route('/')
def index():
    return jsonify(status='ok', data='hello')


@app.route('/', methods=['POST'])
def minder():
    data = json.loads(request.data)
    logger.info(data)

    try:
        toggle, item = _parse_request(data['request'])
        speech_output = 'you\'ve turned {} the {}'.format(toggle, item)
        card_output = 'user turned {} the {}'.format(toggle, item)
        reprompt_message = 'reprompt message. how does this work?'

        db.set_item(item, toggle)
        send_sms(Config.USER_PHONE_NUMBER, card_output)
        response = _get_echo_response(speech_output, card_output, reprompt_message)
    except Exception:
        speech_output = 'sorry, i didn\'t understand that. please try again'
        card_output = 'couldn\'t understand command from user'
        reprompt_message = 'reprompt message. how does this work?'
        response = _get_echo_response(speech_output, card_output, reprompt_message)
    return jsonify(response)


def _parse_request(request):
    request_type = request['type']
    if request_type != 'IntentRequest':
        raise Exception()

    intent = request.get('intent', {})
    if intent.get('name') != 'ItemToggle':
        raise Exception('no intent provided or unknown intent name')

    slots = intent['slots']
    return slots['toggle']['value'], slots['item']['value']


@app.route('/oauth2_callback')
def oauth2_callback():
    flow = client.flow_from_clientsecrets(
      'client_secret.json',
      scope='https://www.googleapis.com/auth/calendar.readonly',
      redirect_uri=flask.url_for('oauth2_callback', _external=True))

    if 'code' not in flask.request.args:
        auth_uri = flow.step1_get_authorize_url()
        return flask.redirect(auth_uri)
    else:
        auth_code = flask.request.args.get('code')
        credentials = flow.step2_exchange(auth_code)
        flask.session['credentials'] = credentials.to_json()
        return flask.redirect(flask.url_for('calendar'))


@app.route('/calendar')
def calendar():

    if 'credentials' not in flask.session:
        return flask.redirect(flask.url_for('oauth2_callback'))
    
    credentials = client.OAuth2Credentials.from_json(flask.session['credentials'])
    
    if credentials.access_token_expired:
        return flask.redirect(flask.url_for('oauth2_callback'))
    else:
        http_auth = credentials.authorize(httplib2.Http())
        calendar_service = discovery.build('calendar', 'v3', http_auth)
        response = calendar_service.events().list(calendarId='primary').execute()
        
        return jsonify(status='ok', events=response.get('items'))

@app.route('/dummy_job')
def dummy_job():
    from job import dummy_job
    job = q.enqueue_call(func=dummy_job, args=(), result_ttl=Config.WORKER_TTL))
    logger.info('Enqueued job: {}'.format(job.get_id()))

if __name__ == '__main__':
    import uuid
    app.secret_key = str(uuid.uuid4())
    app.run(port=Config.PORT, debug=True)
