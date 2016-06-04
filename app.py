import logging
import json
import flask
import httplib2
from flask import Flask, jsonify, request

from config import Config
from log import configure
from apiclient import discovery
from oauth2client import client



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

    response = _parse_request(data['request'])
    return jsonify(response)


def _parse_request(request):
    request_type = request['type']
    if request_type != 'IntentRequest':
        raise Exception()

    intent = request['intent']
    if intent['name'] != 'ItemToggle':
        raise Exception('unknown intent name')

    slots = intent['slots']
    item = slots['item']['value']
    toggle = slots['toggle']['value']

    speech_output = 'you\'ve turned {} the {}'.format(toggle, item)
    card_output = 'user turned {} the {}'.format(toggle, item)
    reprompt_message = 'reprompt message. how does this work?'

    return _get_echo_response(speech_output, card_output, reprompt_message)


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

if __name__ == '__main__':
	import uuid
	app.secret_key = str(uuid.uuid4())
	app.run(port=Config.PORT, debug=True)
